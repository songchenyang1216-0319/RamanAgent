from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.planning import LLMPlanner, ToolCatalog
from backend.db.database import get_db_connection, init_agent_memory_db
from backend.raman_pipeline import PipelineRequest, RamanPipelineRunner
from backend.services.file_processor import FileProcessorRegistry
from backend.services.rag import EmbeddingService, RAGService, VectorStore
from backend.services.rag.retriever import RAGRetriever
from raman_core.methanol.config import OUTPUT_DIR, PROJECT_ROOT, ensure_dirs


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _summary(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "avg_ms": 0, "min_ms": 0, "max_ms": 0}
    return {"count": len(values), "avg_ms": round(statistics.mean(values), 2), "min_ms": min(values), "max_ms": max(values)}


def benchmark_agent(iterations: int) -> dict:
    normalizer = MessageNormalizer()
    planner = LLMPlanner(use_external_model=False, mode="mock")
    catalog = ToolCatalog()
    planner_latencies: list[int] = []
    total_latencies: list[int] = []
    routes: list[str] = []
    for _ in range(iterations):
        started = time.perf_counter()
        normalized = normalizer.normalize({"message": "根据上传的文档总结主要结论。", "conversation_id": "bench_conv", "file_path": "demo.md", "debug": False})
        plan_started = time.perf_counter()
        output = planner.plan(normalized, catalog)
        planner_latencies.append(_ms(plan_started))
        total_latencies.append(_ms(started))
        routes.append(output.plan.plan_type)
    return {
        "iterations": iterations,
        "planner_latency": _summary(planner_latencies),
        "total_request_routing_latency": _summary(total_latencies),
        "routes": routes,
    }


def benchmark_rag(output_dir: Path) -> dict:
    user_id = f"bench_user_{uuid4().hex}"
    conversation_id = f"bench_conv_{uuid4().hex}"
    file_id = f"bench_file_{uuid4().hex}"
    source = output_dir / "rag_benchmark_fact.md"
    source.write_text(
        "RamanAgent demo benchmark fact: RA-BENCH-2026.\n"
        "The benchmark document is intentionally tiny and deterministic.\n",
        encoding="utf-8",
    )
    parse_started = time.perf_counter()
    processed = FileProcessorRegistry().process(source, file_id=file_id, user_id=user_id, conversation_id=conversation_id)
    parse_ms = _ms(parse_started)
    embedding_provider = os.getenv("DEMO_BENCHMARK_EMBEDDING_PROVIDER") or "mock"
    vector_provider = os.getenv("DEMO_BENCHMARK_VECTOR_DB_PROVIDER") or "mock"
    embedding = EmbeddingService(provider=embedding_provider, model=os.getenv("DEMO_BENCHMARK_EMBEDDING_MODEL", "mock-hash-embedding"))
    vector = VectorStore(provider=vector_provider, persist_dir=output_dir / "vectors")
    retriever = RAGRetriever(embedding_service=embedding, vector_store=vector, score_threshold=0.0)
    service = RAGService(embedding_service=embedding, vector_store=vector, retriever=retriever)
    index_started = time.perf_counter()
    index = service.index_file(file_id, user_id, conversation_id)
    index_ms = _ms(index_started)
    retrieve_started = time.perf_counter()
    search = service.search("What is the benchmark fact code?", user_id, conversation_id, file_ids=[file_id])
    retrieve_ms = _ms(retrieve_started)
    no_answer = service.answer_with_rag("What is the lunar mining schedule?", user_id, conversation_id, file_ids=["missing"])
    hit = any("RA-BENCH-2026" in chunk.text for chunk in search.chunks)
    citation_ok = bool(search.citations and search.citations[0].get("file_name") == source.name)
    return {
        "parse_ms": parse_ms,
        "chunk_count": len(processed.chunks or []),
        "embedding_provider": embedding.provider,
        "vector_provider": vector.provider,
        "index_success": index.success,
        "index_ms": index_ms,
        "retrieval_ms": retrieve_ms,
        "hit_rate": 1.0 if hit else 0.0,
        "no_answer_accuracy": 1.0 if (not no_answer.success and "资料中未找到足够依据" in no_answer.answer) else 0.0,
        "citation_accuracy": 1.0 if citation_ok else 0.0,
        "retrieval_mode": search.retrieval_mode,
        "source_breakdown": search.source_breakdown,
    }


def benchmark_raman() -> dict:
    runner = RamanPipelineRunner()
    input_csv = PROJECT_ROOT / "data" / "demo" / "raman_demo_valid.csv"
    started = time.perf_counter()
    result = runner.run(PipelineRequest(file_path=str(input_csv), template_id="basic_preprocessing", save_history=False))
    return {
        "input_csv": _rel(input_csv),
        "success": result.success,
        "total_elapsed_ms": _ms(started),
        "pipeline_elapsed_ms": result.elapsed_ms,
        "step_count": result.total_steps,
        "completed_steps": result.completed_steps,
        "step_elapsed_ms": {step.algorithm_id: step.elapsed_ms for step in result.steps},
        "invalid_file_detection": _invalid_file_detection(runner),
    }


def _invalid_file_detection(runner: RamanPipelineRunner) -> float:
    invalid = PROJECT_ROOT / "data" / "demo" / "raman_demo_invalid.csv"
    result = runner.run(PipelineRequest(file_path=str(invalid), template_id="basic_preprocessing", save_history=False))
    return 1.0 if not result.success and result.error_message else 0.0


def run(iterations: int, output_dir: Path) -> dict:
    ensure_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    init_agent_memory_db()
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "environment": {
            "python": os.sys.version.split()[0],
            "vector_provider": os.getenv("DEMO_BENCHMARK_VECTOR_DB_PROVIDER") or "mock",
            "embedding_provider": os.getenv("DEMO_BENCHMARK_EMBEDDING_PROVIDER") or "mock",
            "llm_planner_mode": os.getenv("LLM_PLANNER_MODE", "hybrid"),
        },
        "agent": benchmark_agent(iterations),
        "rag": benchmark_rag(output_dir),
        "raman": benchmark_raman(),
    }
    json_path = output_dir / "demo_benchmark.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["json_path"] = _rel(json_path)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic RamanAgent demo benchmark.")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR / "demo_benchmark"))
    args = parser.parse_args()
    payload = run(max(1, args.iterations), Path(args.output_dir))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
