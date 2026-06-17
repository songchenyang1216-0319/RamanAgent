# Raman 模型训练与注册

## 目标

训练模块提供候选模型训练、评估、导出和注册能力。它不替代当前核心预测入口 `MethanolPredictor.predict`，而是为后续模型迭代提供产品化通道。

核心文件：

- `backend/raman_training/training_pipeline.py`
- `backend/raman_training/train_registry.py`
- `backend/raman_training/model_evaluator.py`
- `backend/raman_training/model_exporter.py`

## API

```text
POST /api/raman/training/run
GET /api/raman/models
GET /api/raman/models/{model_id}
POST /api/raman/models/{model_id}/activate
```

## 当前模型类型

- `SVR`
- `RandomForestRegressor`
- `PLSRegression`
- `Ridge`
- `Lasso`
- `LinearRegression`
- `KNNRegressor`

`1D-CNN` 当前保留为占位项，需要补齐训练数据格式和 PyTorch 训练实现后再开放。

## 产物

模型文件导出到 `artifacts/`，注册信息写入：

```text
storage/raman_training_models.json
```

不要删除 `artifacts/`，也不要覆盖 `data/raw/` 原始数据。
