import sys
from pathlib import Path

import matplotlib.pyplot as plt
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from raman_core.methanol.predictor import MethanolPredictor


class RamanApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Raman光谱预测浓度（工程化版）")
        self.resize(1020, 990)

        self.selected_file: str | None = None
        self.last_result: dict | None = None

        try:
            self.predictor = MethanolPredictor()
            self.config = self.predictor.config
            self.init_error = None
        except Exception as exc:
            self.predictor = None
            self.config = None
            self.init_error = str(exc)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        default_text = "请先选择 CSV 文件"
        if self.init_error:
            default_text = f"模型初始化失败：{self.init_error}"
        self.info_label = QLabel(default_text)
        layout.addWidget(self.info_label)

        self.load_button = QPushButton("1. 选择CSV文件")
        layout.addWidget(self.load_button)

        self.preprocess_button = QPushButton("2. 生成第2/3/4张图")
        layout.addWidget(self.preprocess_button)

        self.predict_button = QPushButton("3. 最终回归预测")
        layout.addWidget(self.predict_button)

        self.result_label = QLabel("结果会显示在这里")
        layout.addWidget(self.result_label)

        self.figure, self.axes = plt.subplots(4, 1, figsize=(8, 12))
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self.load_button.clicked.connect(self.load_csv)
        self.preprocess_button.clicked.connect(self.show_preprocess)
        self.predict_button.clicked.connect(self.predict_value)

        self.reset_plot_titles()
        self.figure.tight_layout()
        self.canvas.draw()

    def reset_plot_titles(self):
        titles = [
            self.config.get("title_plot_1", "统一波数轴后的原始光谱") if self.config else "统一波数轴后的原始光谱",
            self.config.get("title_plot_2", "SG平滑 + ALS去基线 + 归一化后光谱") if self.config else "SG平滑 + ALS去基线 + 归一化后光谱",
            self.config.get("title_plot_3", "SG平滑 + ALS去基线 + 归一化 + CDAE去噪后光谱") if self.config else "SG平滑 + ALS去基线 + 归一化 + CDAE去噪后光谱",
            self.config.get("title_plot_4", "最终回归输入光谱（SG平滑 -> CDAE去噪 -> CAE+预测基线 -> 去噪谱-预测基线）") if self.config else "最终回归输入光谱",
        ]
        for ax, title in zip(self.axes, titles):
            ax.clear()
            ax.set_title(title)
            ax.axis("off")

    def load_csv(self):
        if self.predictor is None:
            self.result_label.setText(f"模型初始化失败，无法继续：{self.init_error}")
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "选择CSV文件", "", "CSV Files (*.csv)")
        if not file_path:
            return

        self.selected_file = file_path
        self.last_result = None
        self.reset_plot_titles()
        self.figure.tight_layout()
        self.canvas.draw()
        self.info_label.setText(f"已选择文件：{Path(file_path).name}")
        self.result_label.setText("文件已加载，可以点击第2步或第3步开始推理。")

    def _run_prediction(self) -> dict | None:
        if self.predictor is None:
            self.result_label.setText(f"模型初始化失败，无法继续：{self.init_error}")
            return None
        if not self.selected_file:
            self.result_label.setText("请先选择CSV文件。")
            return None

        try:
            self.last_result = self.predictor.predict(self.selected_file)
            return self.last_result
        except Exception as exc:
            self.result_label.setText(f"预测失败：{exc}")
            return None

    def _show_result_figures(self, result: dict):
        figure_paths = [
            result["figures"]["raw"],
            result["figures"]["preprocessed"],
            result["figures"]["cdae"],
            result["figures"]["final"],
        ]
        titles = [
            self.config.get("title_plot_1", "统一波数轴后的原始光谱"),
            self.config.get("title_plot_2", "SG平滑 + ALS去基线 + 归一化后光谱"),
            self.config.get("title_plot_3", "SG平滑 + ALS去基线 + 归一化 + CDAE去噪后光谱"),
            self.config.get("title_plot_4", "最终回归输入光谱（SG平滑 -> CDAE去噪 -> CAE+预测基线 -> 去噪谱-预测基线）"),
        ]

        for ax, figure_path, title in zip(self.axes, figure_paths, titles):
            ax.clear()
            ax.imshow(plt.imread(figure_path))
            ax.set_title(title)
            ax.axis("off")

        self.figure.tight_layout()
        self.canvas.draw()

    def show_preprocess(self):
        result = self._run_prediction()
        if result is None:
            return

        self._show_result_figures(result)
        self.info_label.setText("第2/3/4张图已生成，当前结果来自 MethanolPredictor。")
        self.result_label.setText(
            "已完成：\n"
            "第2张图 = 统一波数轴 -> SG平滑 -> ALS去基线 -> 归一化\n"
            "第3张图 = 统一波数轴 -> SG平滑 -> ALS去基线 -> 归一化 -> CDAE去噪\n"
            "第4张图 = 统一波数轴 -> SG平滑 -> CDAE去噪 -> CAE+预测基线 -> 去噪谱-预测基线"
        )

    def predict_value(self):
        result = self._run_prediction()
        if result is None:
            return

        self._show_result_figures(result)
        confidence = result["confidence"]
        self.result_label.setText(
            f"SVR预测浓度: {result['svr_prediction']:.4f}    "
            f"RF预测浓度: {result['rf_prediction']:.4f}    "
            f"融合结果: {result['fusion_prediction']:.4f}\n"
            f"编码空间平均近邻距离: {confidence['knn_distance']:.4f}    {confidence['status']}"
        )
        self.info_label.setText("预测已完成，图像与结果均来自 MethanolPredictor.predict。")


if __name__ == "__main__":
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    app = QApplication(sys.argv)
    window = RamanApp()
    window.show()
    sys.exit(app.exec_())
