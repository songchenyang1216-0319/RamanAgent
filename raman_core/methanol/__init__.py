"""甲醇拉曼光谱预测核心模块。"""

__all__ = ["MethanolPredictor"]


def __getattr__(name: str):
    if name == "MethanolPredictor":
        from .predictor import MethanolPredictor

        return MethanolPredictor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
