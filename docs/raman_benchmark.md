# Raman Benchmark

## 目标

Raman Benchmark 用于把一组 Raman CSV 文件固定成测试集，并对一个或多个 Pipeline 做批量回归验证。

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
