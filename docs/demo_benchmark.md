# RamanAgent Demo Benchmark

该 benchmark 只记录当前机器上的真实本地测试数据，不伪造 QPS、准确率或覆盖率。默认使用 mock embedding/vector store，适合 CI 和离线演示；如需真实 Chroma + local embedding，请先配置环境变量。

## 运行

```powershell
python -m scripts.run_demo_benchmark --iterations 3
```

输出文件：

- `outputs/demo_benchmark/demo_benchmark.json`

## 指标

Agent：Planner 延迟、路由总延迟、路由结果。

RAG：文档解析时间、分块数量、索引时间、检索时间、hit rate、no-answer accuracy、citation accuracy、retrieval mode。

Raman：单文件预处理时间、每个算法节点耗时、Pipeline 总耗时、成功率、无效文件识别率。

## 真实 Chroma + local embedding 手动模式

```powershell
$env:DEMO_BENCHMARK_VECTOR_DB_PROVIDER = "chroma"
$env:VECTOR_DB_DIR = "storage/vector_db"
$env:DEMO_BENCHMARK_EMBEDDING_PROVIDER = "local"
$env:DEMO_BENCHMARK_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
python -m scripts.run_demo_benchmark --iterations 3
```

首次运行 local embedding 可能需要下载模型，耗时取决于网络和本机硬件。
