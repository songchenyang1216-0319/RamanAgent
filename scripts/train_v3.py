import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

from raman_core.methanol.confidence import calc_train_distance_threshold
from raman_core.methanol.config import ARTIFACT_DIR, RAW_DATA_DIR, ensure_dirs
from raman_core.methanol.models import BASELINE_POWER, TARGET_LENGTH, CAEPlusBaseline, ConvAutoEncoder
from raman_core.methanol.preprocess import (
    ALS_LAM,
    ALS_NITER,
    ALS_P,
    add_baseline_distortion,
    add_fluorescence_background,
    add_noise,
    add_spikes,
    augment_spectrum,
    baseline_als_for_pseudo_label,
    correct_by_baseline,
    preprocess_for_als_branch,
    preprocess_for_regression_branch,
)
from raman_core.methanol.spectrum_io import load_labeled_spectra


DATA_FOLDER = Path(os.getenv("RAMAN_DATA_FOLDER", str(RAW_DATA_DIR)))
RANDOM_STATE = 42
TEST_SIZE = 0.2

CDAE_EPOCHS = 80
CDAE_BATCH_SIZE = 32
CDAE_LR = 1e-3
AUG_COPIES = 5

CAEPLUS_EPOCHS = 100
CAEPLUS_BATCH_SIZE = 32
CAEPLUS_LR = 5e-4

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SG_WINDOWS = [7, 9, 11, 15, 21]
SG_ORDERS = [2, 3, 4]

SVR_WEIGHT = 0.6
RF_WEIGHT = 0.4


@dataclass
class SpectrumPairDataset:
    inputs: np.ndarray
    targets: np.ndarray


def set_seed(seed: int = RANDOM_STATE) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def tune_sg_params(x_train_raw: np.ndarray, y_train: np.ndarray) -> Tuple[int, int]:
    print("\n开始搜索最优 SG 参数...")
    best_score = np.inf
    best_pair = (11, 2)
    kf = KFold(n_splits=3, shuffle=True, random_state=RANDOM_STATE)

    for window in SG_WINDOWS:
        for order in SG_ORDERS:
            if order >= window:
                continue

            processed = np.array(
                [preprocess_for_regression_branch(spectrum, window, order) for spectrum in x_train_raw],
                dtype=np.float32,
            )
            fold_rmses = []

            for tr_idx, va_idx in kf.split(processed):
                x_tr, x_va = processed[tr_idx], processed[va_idx]
                y_tr, y_va = y_train[tr_idx], y_train[va_idx]

                scaler = StandardScaler()
                x_tr = scaler.fit_transform(x_tr)
                x_va = scaler.transform(x_va)

                model = SVR(kernel="rbf", C=10, gamma="scale")
                model.fit(x_tr, y_tr)
                pred = model.predict(x_va)
                fold_rmses.append(np.sqrt(mean_squared_error(y_va, pred)))

            mean_rmse = float(np.mean(fold_rmses))
            print(f"SG(window={window}, order={order}) -> CV RMSE = {mean_rmse:.4f}")
            if mean_rmse < best_score:
                best_score = mean_rmse
                best_pair = (window, order)

    print(f"最优 SG 参数: window={best_pair[0]}, order={best_pair[1]}, CV RMSE={best_score:.4f}\n")
    return best_pair


def build_cdae_dataset(clean_train: np.ndarray, aug_copies: int = AUG_COPIES) -> SpectrumPairDataset:
    rng = np.random.default_rng(RANDOM_STATE)
    noisy_samples = []
    clean_samples = []

    for clean in clean_train:
        noisy_samples.append(clean)
        clean_samples.append(clean)
        for _ in range(aug_copies):
            noisy_samples.append(augment_spectrum(clean, rng))
            clean_samples.append(clean)

    return SpectrumPairDataset(
        inputs=np.stack(noisy_samples).astype(np.float32),
        targets=np.stack(clean_samples).astype(np.float32),
    )


def train_cdae(clean_train: np.ndarray, model_name: str) -> ConvAutoEncoder:
    dataset = build_cdae_dataset(clean_train)
    x_noisy = torch.tensor(dataset.inputs[:, None, :], dtype=torch.float32)
    x_clean = torch.tensor(dataset.targets[:, None, :], dtype=torch.float32)

    total = x_noisy.shape[0]
    indices = np.arange(total)
    rng = np.random.default_rng(RANDOM_STATE)
    rng.shuffle(indices)
    split = int(total * 0.9)
    tr_idx, va_idx = indices[:split], indices[split:]

    train_noisy, train_clean = x_noisy[tr_idx], x_clean[tr_idx]
    val_noisy, val_clean = x_noisy[va_idx], x_clean[va_idx]

    model = ConvAutoEncoder(input_length=TARGET_LENGTH).to(DEVICE)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=CDAE_LR)

    best_val = np.inf
    best_state = None
    patience = 12
    wait = 0

    print(f"开始训练 {model_name}...")
    for epoch in range(1, CDAE_EPOCHS + 1):
        model.train()
        perm = torch.randperm(train_noisy.size(0))
        epoch_losses = []

        for i in range(0, train_noisy.size(0), CDAE_BATCH_SIZE):
            batch_idx = perm[i:i + CDAE_BATCH_SIZE]
            xb = train_noisy[batch_idx].to(DEVICE)
            yb = train_clean[batch_idx].to(DEVICE)

            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            optimizer.step()
            epoch_losses.append(loss.item())

        model.eval()
        with torch.no_grad():
            val_pred = model(val_noisy.to(DEVICE))
            val_loss = criterion(val_pred, val_clean.to(DEVICE)).item()

        train_loss = float(np.mean(epoch_losses))
        print(f"[{model_name}] Epoch {epoch:03d}/{CDAE_EPOCHS} | train_loss={train_loss:.6f} | val_loss={val_loss:.6f}")

        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                print(f"{model_name} 触发早停。")
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def run_cdae(model: ConvAutoEncoder, arr: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        tensor = torch.tensor(arr[:, None, :], dtype=torch.float32).to(DEVICE)
        out = model(tensor).cpu().numpy()[:, 0, :]
    return out.astype(np.float32)


def encode_with_cdae(model: ConvAutoEncoder, arr: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        tensor = torch.tensor(arr[:, None, :], dtype=torch.float32).to(DEVICE)
        lat = model.encode_vector(tensor).cpu().numpy()
    return lat.astype(np.float32)


def build_caeplus_dataset(denoised_train: np.ndarray) -> SpectrumPairDataset:
    baseline_targets = []
    for spec in denoised_train:
        baseline_targets.append(baseline_als_for_pseudo_label(spec))
    return SpectrumPairDataset(
        inputs=denoised_train.astype(np.float32),
        targets=np.stack(baseline_targets).astype(np.float32),
    )


def train_caeplus(denoised_train: np.ndarray) -> CAEPlusBaseline:
    dataset = build_caeplus_dataset(denoised_train)
    x_in = torch.tensor(dataset.inputs[:, None, :], dtype=torch.float32)
    y_bl = torch.tensor(dataset.targets[:, None, :], dtype=torch.float32)

    total = x_in.shape[0]
    indices = np.arange(total)
    rng = np.random.default_rng(RANDOM_STATE)
    rng.shuffle(indices)
    split = int(total * 0.9)
    tr_idx, va_idx = indices[:split], indices[split:]

    train_in, train_bl = x_in[tr_idx], y_bl[tr_idx]
    val_in, val_bl = x_in[va_idx], y_bl[va_idx]

    model = CAEPlusBaseline(baseline_power=BASELINE_POWER).to(DEVICE)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=CAEPLUS_LR)

    best_val = np.inf
    best_state = None
    patience = 15
    wait = 0

    print("开始训练 CAE+（负责预测基线）...")
    for epoch in range(1, CAEPLUS_EPOCHS + 1):
        model.train()
        perm = torch.randperm(train_in.size(0))
        epoch_losses = []

        for i in range(0, train_in.size(0), CAEPLUS_BATCH_SIZE):
            batch_idx = perm[i:i + CAEPLUS_BATCH_SIZE]
            xb = train_in[batch_idx].to(DEVICE)
            yb = train_bl[batch_idx].to(DEVICE)

            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            optimizer.step()
            epoch_losses.append(loss.item())

        model.eval()
        with torch.no_grad():
            val_pred = model(val_in.to(DEVICE))
            val_loss = criterion(val_pred, val_bl.to(DEVICE)).item()

        train_loss = float(np.mean(epoch_losses))
        print(f"[CAE+] Epoch {epoch:03d}/{CAEPLUS_EPOCHS} | train_loss={train_loss:.6f} | val_loss={val_loss:.6f}")

        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                print("CAE+ 触发早停。")
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def run_caeplus(model: CAEPlusBaseline, arr: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        tensor = torch.tensor(arr[:, None, :], dtype=torch.float32).to(DEVICE)
        out = model(tensor).cpu().numpy()[:, 0, :]
    return out.astype(np.float32)


def evaluate_regression(y_true: np.ndarray, y_pred: np.ndarray, name: str) -> Dict[str, float]:
    metrics = {
        "R2": float(r2_score(y_true, y_pred)),
        "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "MAE": float(mean_absolute_error(y_true, y_pred)),
    }
    print(name)
    for key, value in metrics.items():
        print(f"{key}: {value:.6f}")
    print()
    return metrics


def main() -> None:
    set_seed(RANDOM_STATE)
    ensure_dirs()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    x_all_raw, y_all, common_axis, _ = load_labeled_spectra(DATA_FOLDER, target_length=TARGET_LENGTH)
    print(f"读取到 {len(x_all_raw)} 条有效光谱。")
    print(f"统一波数轴长度: {len(common_axis)}")

    idx = np.arange(len(x_all_raw))
    train_idx, test_idx = train_test_split(idx, test_size=TEST_SIZE, random_state=RANDOM_STATE)

    x_train_raw, x_test_raw = x_all_raw[train_idx], x_all_raw[test_idx]
    y_train, y_test = y_all[train_idx], y_all[test_idx]

    sg_window, sg_order = tune_sg_params(x_train_raw, y_train)

    x_train_als_pre = np.array(
        [preprocess_for_als_branch(s, sg_window, sg_order, lam=ALS_LAM, p=ALS_P, niter=ALS_NITER)[0] for s in x_train_raw],
        dtype=np.float32,
    )
    x_train_reg_pre = np.array([preprocess_for_regression_branch(s, sg_window, sg_order) for s in x_train_raw], dtype=np.float32)
    x_test_reg_pre = np.array([preprocess_for_regression_branch(s, sg_window, sg_order) for s in x_test_raw], dtype=np.float32)

    cdae_display_model = train_cdae(x_train_als_pre, model_name="CDAE-ALS分支")
    cdae_reg_model = train_cdae(x_train_reg_pre, model_name="CDAE-回归分支")

    x_train_reg_denoised = run_cdae(cdae_reg_model, x_train_reg_pre)
    x_test_reg_denoised = run_cdae(cdae_reg_model, x_test_reg_pre)

    caeplus_model = train_caeplus(x_train_reg_denoised)
    train_baseline = run_caeplus(caeplus_model, x_train_reg_denoised)
    test_baseline = run_caeplus(caeplus_model, x_test_reg_denoised)

    x_train_corrected = correct_by_baseline(x_train_reg_denoised, train_baseline)
    x_test_corrected = correct_by_baseline(x_test_reg_denoised, test_baseline)

    scaler = StandardScaler()
    x_train_std = scaler.fit_transform(x_train_corrected)
    x_test_std = scaler.transform(x_test_corrected)

    svr_model = SVR(kernel="rbf", C=20, gamma="scale")
    svr_model.fit(x_train_std, y_train)
    svr_pred = svr_model.predict(x_test_std)

    rf_model = RandomForestRegressor(n_estimators=300, random_state=RANDOM_STATE)
    rf_model.fit(x_train_std, y_train)
    rf_pred = rf_model.predict(x_test_std)

    fusion_pred = SVR_WEIGHT * svr_pred + RF_WEIGHT * rf_pred

    metrics = {
        "SVR": evaluate_regression(y_test, svr_pred, "SVR 结果"),
        "RF": evaluate_regression(y_test, rf_pred, "Random Forest 结果"),
        "Fusion": evaluate_regression(y_test, fusion_pred, "融合结果"),
    }

    latent_train = encode_with_cdae(cdae_reg_model, x_train_reg_pre)
    distance_threshold = calc_train_distance_threshold(latent_train, k=5, percentile=95.0)
    print(f"可信度距离阈值: {distance_threshold:.6f}")

    torch.save(cdae_display_model.state_dict(), ARTIFACT_DIR / "cdae_display_model.pt")
    torch.save(cdae_reg_model.state_dict(), ARTIFACT_DIR / "cdae_reg_model.pt")
    torch.save(caeplus_model.state_dict(), ARTIFACT_DIR / "caeplus_model.pt")
    np.save(ARTIFACT_DIR / "common_axis.npy", common_axis)
    np.save(ARTIFACT_DIR / "latent_train.npy", latent_train)
    joblib.dump(svr_model, ARTIFACT_DIR / "svr_model.pkl")
    joblib.dump(rf_model, ARTIFACT_DIR / "rf_model.pkl")
    joblib.dump(scaler, ARTIFACT_DIR / "scaler.pkl")

    config = {
        "target_length": TARGET_LENGTH,
        "sg_window": sg_window,
        "sg_order": sg_order,
        "als_lam": ALS_LAM,
        "als_p": ALS_P,
        "als_niter": ALS_NITER,
        "device": DEVICE,
        "svr_weight": SVR_WEIGHT,
        "rf_weight": RF_WEIGHT,
        "distance_threshold": distance_threshold,
        "metrics": metrics,
        "artifact_dir": str(ARTIFACT_DIR),
        "baseline_power": BASELINE_POWER,
        "title_plot_1": "统一波数轴后的原始光谱",
        "title_plot_2": "SG平滑 + ALS去基线 + 归一化后光谱",
        "title_plot_3": "SG平滑 + ALS去基线 + 归一化 + CDAE去噪后光谱",
        "title_plot_4": "最终回归输入光谱（SG平滑 -> CDAE去噪 -> CAE+预测基线 -> 去噪谱-预测基线）",
        "pipeline_plot_2": "统一波数轴 -> SG平滑 -> ALS去基线 -> 归一化",
        "pipeline_plot_3": "统一波数轴 -> SG平滑 -> ALS去基线 -> 归一化 -> CDAE去噪",
        "pipeline_plot_4": "统一波数轴 -> SG平滑 -> CDAE去噪 -> CAE+预测基线 -> 去噪谱-预测基线 -> 最终回归预测",
    }
    with open(ARTIFACT_DIR / "config.json", "w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)

    print(f"\n训练数据目录: {DATA_FOLDER}")
    print("第2张图：SG平滑 + ALS去基线 + 归一化")
    print("第3张图：SG平滑 + ALS去基线 + 归一化 + CDAE去噪")
    print("第4张图：SG平滑 + CDAE去噪 + CAE+预测基线 + 去噪谱减基线")
    print("训练完成。")


if __name__ == "__main__":
    main()
