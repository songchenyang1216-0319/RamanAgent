from __future__ import annotations

import hashlib
import importlib.util
import math
import os
from typing import Any


class EmbeddingService:
    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        dim: int | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.provider = str(provider or os.getenv("EMBEDDING_PROVIDER") or "mock").strip().lower()
        self.model = str(model or os.getenv("EMBEDDING_MODEL") or "mock-hash-embedding").strip()
        self.dim = max(16, int(dim or os.getenv("EMBEDDING_DIM") or 384))
        self.base_url = base_url or os.getenv("EMBEDDING_BASE_URL") or ""
        self.api_key = api_key if api_key is not None else os.getenv("EMBEDDING_API_KEY", "")
        self.timeout_seconds = float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "30") or 30)
        self.batch_size = max(1, int(os.getenv("EMBEDDING_BATCH_SIZE", os.getenv("RAG_EMBEDDING_BATCH_SIZE", "64")) or 64))
        self._local_model: Any = None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        texts = [str(text or "") for text in texts]
        if not texts:
            return []
        if self.provider == "mock":
            return [self._mock_embed(text) for text in texts]
        if self.provider == "local":
            return self._batched(texts, self._local_embed)
        if self.provider == "remote":
            return self._batched(texts, self._remote_embed)
        raise RuntimeError(f"不支持的 embedding provider: {self.provider}")

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]

    def get_model_info(self) -> dict[str, Any]:
        app_env = str(os.getenv("APP_ENV", "development") or "development").lower()
        warnings = []
        if app_env == "production" and self.provider == "mock":
            warnings.append("生产环境不建议使用 mock embedding，请配置 EMBEDDING_PROVIDER=local 或 remote。")
        if self.provider == "remote" and not self.api_key:
            warnings.append("远程 embedding 未配置 EMBEDDING_API_KEY。")
        if self.provider == "local" and importlib.util.find_spec("sentence_transformers") is None:
            warnings.append("本地 embedding 需要安装 sentence-transformers，并确保 EMBEDDING_MODEL 可加载。")
        return {
            "embedding_provider": self.provider,
            "embedding_model": self.model,
            "embedding_dim": self.dim,
            "embedding_is_mock": self.provider == "mock",
            "embedding_batch_size": self.batch_size,
            "embedding_timeout_seconds": self.timeout_seconds,
            "app_env": app_env,
            "production_ready": not warnings,
            "warnings": warnings,
        }

    def _batched(self, texts: list[str], handler) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            embeddings.extend(handler(texts[start : start + self.batch_size]))
        return embeddings

    def _mock_embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = [token for token in str(text or "").lower().replace("\n", " ").split(" ") if token]
        if not tokens:
            tokens = [str(text or "empty")]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
            for offset in range(0, min(len(digest), 32), 4):
                bucket = int.from_bytes(digest[offset : offset + 4], "big") % self.dim
                sign = 1.0 if digest[offset] % 2 == 0 else -1.0
                vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _local_embed(self, texts: list[str]) -> list[list[float]]:
        try:
            from sentence_transformers import SentenceTransformer
        except ModuleNotFoundError as exc:
            raise RuntimeError("当前环境缺少 sentence-transformers，无法使用本地 embedding。") from exc
        if self._local_model is None:
            try:
                self._local_model = SentenceTransformer(self.model)
            except Exception as exc:
                raise RuntimeError(f"本地 embedding 模型加载失败：{exc}") from exc
        embeddings = self._local_model.encode(texts, normalize_embeddings=True)
        return [list(map(float, row)) for row in embeddings]

    def _remote_embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("远程 embedding 未配置 EMBEDDING_API_KEY。")
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError("当前环境缺少 openai SDK，无法使用远程 embedding。") from exc
        client = OpenAI(api_key=self.api_key, base_url=self.base_url or None, timeout=self.timeout_seconds)
        response = client.embeddings.create(model=self.model, input=texts)
        return [list(map(float, item.embedding)) for item in response.data]
