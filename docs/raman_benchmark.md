# Raman Benchmark

## 目标

Raman Benchmark 用于把 Raman CSV 固定成可复现测试集，对不同预处理 Pipeline 做批量对比。它不是为了替代模型训练评测，而是为了面试和 demo 时清楚说明：同一条光谱经过 raw、SG、ALS、归一化和完整 Pipeline 后，步骤、耗时、metrics、图像产物和错误处理都可追踪。

核心文件：

- `backend/raman_evaluation/benchmark_runner.py`
- `backend/raman_evaluation/metrics.py`
- `backend/api/raman_benchmark_api.py`

## API

```text
GET /api/raman/datasets
POST /api/raman/datasets
POST /api/raman/benchmark/run
GET /api/raman/benchmark/{benchmark_id}
```

前端入口：

```text
Raman Benchmark / 训练
```

## 数据集

数据集记录在：

```text
storage/raman_datasets.json
```

字段包括：

- `dataset_id`
- `name`
- `files`
- `sample_count`
- `target_type`
- `target_name`
- `labels`

## Benchmark 输出

运行历史记录在：

```text
storage/raman_benchmarks.json
```

输出包括每个文件、每条 Pipeline 的成功状态、错误信息、耗时和步骤摘要。

## 本地脚本

仓库提供一个不依赖外网模型的 demo benchmark：

```powershell
python -B scripts/run_raman_benchmark.py
```

默认输入：

```text
data/demo/demo_raman_methanol.csv
```

默认输出：

```text
outputs/raman_benchmark/raman_benchmark.json
outputs/raman_benchmark/raman_benchmark.csv
outputs/raman_pipeline/<run_id>/*.png
```

## 对比 Pipeline

- `raw`：只读取和校验原始光谱。
- `sg_smoothing`：Savitzky-Golay 平滑。
- `als_baseline`：ALS 基线估计与扣除。
- `sg_plus_als`：SG 平滑后做 ALS 去基线。
- `normalize`：Min-Max 归一化。
- `full_preprocessing_pipeline`：清洗、排序、去重、SG、ALS、归一化、峰识别和质量评估。

## Demo 讲解口径

面试演示时可以先运行脚本生成 JSON/CSV，再打开前端 Pipeline 面板运行 `basic_preprocessing`、`peak_analysis`、`quality_check`。重点讲清楚三件事：

1. 每个算法节点都有统一输入输出 shape、metrics、warning/error 和 artifacts。
2. 深度学习算法没有模型文件时会明确标记不可用，不会伪装成功。
3. 旧的 `MethanolPredictor.predict` 仍是核心预测入口，Pipeline Builder 是可组合分析与可视化层。
