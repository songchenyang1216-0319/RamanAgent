"""甲醇含量预测入口。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import torch

from .confidence import calculate_confidence
from .config import ARTIFACT_DIR, ensure_dirs
from .models import CAEPlusBaseline, ConvAutoEncoder
from .preprocess import correct_by_baseline, interpolate_to_axis, preprocess_for_als_branch, preprocess_for_cdae_branch
from .spectrum_io import read_csv_spectrum
from .visualization import save_stage_figures


class MethanolPredictor:
    """封装甲醇拉曼光谱推理流程。"""

    def __init__(self, artifact_dir: str | Path | None = None, device: str | None = None):
        ensure_dirs()
        self.artifact_dir = Path(artifact_dir) if artifact_dir is not None else ARTIFACT_DIR
        self.legacy_artifact_dir = ARTIFACT_DIR
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.config = self._load_config()
        self.common_axis = self._load_numpy("common_axis.npy")
        self.latent_train = self._load_numpy("latent_train.npy")
        self.svr_model = self._load_joblib("svr_model.pkl")
        self.rf_model = self._load_joblib("rf_model.pkl")
        self.scaler = self._load_joblib("scaler.pkl")
        self.cdae_display_model = self._load_cdae_model("cdae_display_model.pt")
        self.cdae_reg_model = self._load_cdae_model("cdae_reg_model.pt")
        self.caeplus_model = self._load_caeplus_model("caeplus_model.pt")

    def _resolve_artifact(self, file_name: str) -> Path:
        path = self.artifact_dir / file_name
        if path.exists():
            return path
        legacy_path = self.legacy_artifact_dir / file_name
        if legacy_path.exists():
            return legacy_path
        raise FileNotFoundError(f"模型或配置文件不存在: {path}")

    def _load_config(self) -> dict[str, Any]:
        config_path = self._resolve_artifact("config.json")
        with open(config_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def _load_numpy(self, file_name: str) -> np.ndarray:
        return np.load(self._resolve_artifact(file_name))

    def _load_joblib(self, file_name: str) -> Any:
        return joblib.load(self._resolve_artifact(file_name))

    def _load_cdae_model(self, file_name: str) -> ConvAutoEncoder:
        model = ConvAutoEncoder(input_length=int(self.config["target_length"]))
        state_dict = torch.load(self._resolve_artifact(file_name), map_location=self.device)
        model.load_state_dict(state_dict)
        model.to(self.device)
        model.eval()
        return model

    def _load_caeplus_model(self, file_name: str) -> CAEPlusBaseline:
        model = CAEPlusBaseline(baseline_power=float(self.config.get("baseline_power", 1.0)))
        state_dict = torch.load(self._resolve_artifact(file_name), map_location=self.device)
        model.load_state_dict(state_dict)
        model.to(self.device)
        model.eval()
        return model

    def _run_cdae_single(self, model: ConvAutoEncoder, arr: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            tensor = torch.tensor(arr[None, None, :], dtype=torch.float32).to(self.device)
            return model(tensor).cpu().numpy()[0, 0, :].astype(np.float32)

    def _run_caeplus_single(self, arr: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            tensor = torch.tensor(arr[None, None, :], dtype=torch.float32).to(self.device)
            return self.caeplus_model(tensor).cpu().numpy()[0, 0, :].astype(np.float32)

    def _encode_single(self, arr: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            tensor = torch.tensor(arr[None, None, :], dtype=torch.float32).to(self.device)
            return self.cdae_reg_model.encode_vector(tensor).cpu().numpy()[0].astype(np.float32)

    def predict(self, file_path: str | Path) -> dict[str, Any]:
        """对单个 CSV 光谱执行推理并返回可序列化结果。"""
        path = Path(file_path)
        raw_x, raw_y = read_csv_spectrum(path)
        aligned_y = interpolate_to_axis(raw_x, raw_y, self.common_axis)

        sg_window = int(self.config["sg_window"])
        sg_order = int(self.config["sg_order"])
        als_lam = float(self.config.get("als_lam", 1e5))
        als_p = float(self.config.get("als_p", 0.01))
        als_niter = int(self.config.get("als_niter", 10))

        als_processed_y, _, als_baseline_y = preprocess_for_als_branch(
            aligned_y,
            sg_window=sg_window,
            sg_order=sg_order,
            lam=als_lam,
            p=als_p,
            niter=als_niter,
        )
        denoised_als_y = self._run_cdae_single(self.cdae_display_model, als_processed_y)

        reg_processed_y = preprocess_for_cdae_branch(aligned_y, sg_window=sg_window, sg_order=sg_order)
        denoised_reg_y = self._run_cdae_single(self.cdae_reg_model, reg_processed_y)
        estimated_baseline = self._run_caeplus_single(denoised_reg_y)
        corrected_y = correct_by_baseline(denoised_reg_y, estimated_baseline)

        x = corrected_y.reshape(1, -1)
        try:
            x_std = self.scaler.transform(x)
        except Exception as exc:
            raise ValueError(f"输入维度与 scaler 不匹配，无法完成预测: {exc}") from exc

        svr_prediction = float(self.svr_model.predict(x_std)[0])
        rf_prediction = float(self.rf_model.predict(x_std)[0])
        fusion_prediction = float(
            self.config["svr_weight"] * svr_prediction + self.config["rf_weight"] * rf_prediction
        )

        current_latent = self._encode_single(reg_processed_y)
        confidence = calculate_confidence(
            current_latent=current_latent,
            latent_train=self.latent_train,
            threshold=float(self.config["distance_threshold"]),
            k=5,
        )

        figures = save_stage_figures(
            sample_name=path.name,
            common_axis=self.common_axis,
            raw=aligned_y,
            preprocessed=als_processed_y,
            cdae=denoised_als_y,
            final=corrected_y,
            titles=self.config,
        )

        return {
            "sample_file": path.name,
            "sample_path": str(path),
            "svr_prediction": svr_prediction,
            "rf_prediction": rf_prediction,
            "fusion_prediction": fusion_prediction,
            "unit": "percent_or_ppm",
            "confidence": confidence,
            "figures": figures,
            "pipeline": [
                "统一波数轴",
                "SG平滑",
                "ALS去基线",
                "CDAE去噪",
                "CAE+预测基线",
                "SVR/RF融合预测",
            ],
            "intermediate": {
                "aligned_y": aligned_y.tolist(),
                "als_processed_y": als_processed_y.tolist(),
                "als_baseline_y": als_baseline_y.tolist(),
                "denoised_als_y": denoised_als_y.tolist(),
                "reg_processed_y": reg_processed_y.tolist(),
                "denoised_reg_y": denoised_reg_y.tolist(),
                "estimated_baseline": estimated_baseline.tolist(),
                "corrected_y": corrected_y.tolist(),
            },
        }
