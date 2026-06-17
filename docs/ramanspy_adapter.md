# RamanSPy Adapter

`backend/raman_pipeline/adapters/ramanspy_adapter.py` 是 RamanSPy 的 optional adapter，不把 `ramanspy` 加入核心依赖。

## 启用方式

安装可选依赖：

```powershell
pip install ramanspy
```

注册可选算法：

```python
from backend.raman_pipeline.adapters import register_ramanspy_algorithms

status = register_ramanspy_algorithms()
```

## 当前预留算法

- `ramanspy_savgol`
- `ramanspy_aspls`
- `ramanspy_minmax`
- `ramanspy_cropper`
- `ramanspy_whitaker_hayes`

如果未安装 RamanSPy，adapter 会标记 `available=false` 并返回不可用原因，不影响现有 Raman Pipeline。
