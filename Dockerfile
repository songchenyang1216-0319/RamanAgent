FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000 \
    VECTOR_DB_PROVIDER=chroma \
    VECTOR_DB_DIR=/app/storage/vector_db \
    EMBEDDING_PROVIDER=local \
    EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5 \
    RAG_TOP_K=6 \
    RAG_SCORE_THRESHOLD=0.25 \
    RAG_ENABLE_KEYWORD_FALLBACK=true \
    RAG_ENABLE_RERANK=true \
    RAG_RERANK_PROVIDER=lexical \
    OCR_PROVIDER=none \
    PDF_EXPORT_PROVIDER=none

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend
COPY raman_core /app/raman_core
COPY scripts /app/scripts
COPY apps /app/apps
COPY docs /app/docs
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY artifacts /app/artifacts
COPY data /app/data
COPY README.md ARCHITECTURE.md AGENTS.md /app/

RUN mkdir -p /app/storage /app/outputs /app/data/raw /app/data/demo /app/artifacts
RUN addgroup --system ramanagent \
    && adduser --system --ingroup ramanagent ramanagent \
    && chown -R ramanagent:ramanagent /app/storage /app/outputs /app/artifacts

USER ramanagent

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
