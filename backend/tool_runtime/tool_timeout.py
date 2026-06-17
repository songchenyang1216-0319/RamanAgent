from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable, TypeVar

from backend.tool_runtime.tool_errors import ToolRuntimeException


T = TypeVar("T")


def run_with_timeout(func: Callable[[], T], timeout_seconds: int) -> T:
    timeout = max(1, int(timeout_seconds or 60))
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as exc:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise ToolRuntimeException("TOOL_TIMEOUT", f"工具执行超过 {timeout} 秒，已停止等待。") from exc
    finally:
        if future.done():
            executor.shutdown(wait=False, cancel_futures=True)
