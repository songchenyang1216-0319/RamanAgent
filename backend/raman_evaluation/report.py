from __future__ import annotations

from typing import Any


def benchmark_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Raman Benchmark {result.get('benchmark_id')}",
        "",
        f"- 数据集：{result.get('dataset_id')}",
        f"- 运行数：{result.get('total_runs')}",
        f"- 失败率：{result.get('failure_rate')}",
        "",
        "| 文件 | Pipeline | 状态 | SNR | 基线漂移 | 峰数 | 耗时 ms |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in result.get("rows") or []:
        lines.append(
            "| {file} | {pipeline} | {status} | {snr} | {baseline} | {peaks} | {runtime} |".format(
                file=row.get("file"),
                pipeline=row.get("pipeline_name"),
                status="成功" if row.get("success") else "失败",
                snr=row.get("SNR") or "",
                baseline=row.get("baseline_drift_score") or "",
                peaks=row.get("peak_count") or "",
                runtime=row.get("runtime_ms") or "",
            )
        )
    return "\n".join(lines)

