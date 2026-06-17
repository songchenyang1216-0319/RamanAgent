FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000 \
    VECTOR_DB_PROVIDER=mock \
    EMBEDDING_PROVIDER=mock \
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
COPY artifacts /app/artifacts
COPY data /app/data
COPY README.md ARCHITECTURE.md AGENTS.md /app/

RUN mkdir -p /app/storage /app/outputs /app/data/raw /app/data/demo /app/artifacts

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
