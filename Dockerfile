# syntax=docker/dockerfile:1.7
# API and ARQ worker image (same image, different command; see docker-compose.yml).

# ---- build: install Python dependencies into a virtualenv ---------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Compilers only for the rare package without a wheel; they stay in this stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- runtime: slim image, non-root user ---------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    EMBEDDING_CACHE_DIR=/app/.cache/fastembed \
    TESSERACT_CMD=/usr/bin/tesseract

# Tesseract for OCR of scanned documents; libgomp for the ONNX embedding runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY static ./static
# Writable model cache (the embedding model downloads here on first use; mount a volume to keep it).
RUN mkdir -p /app/.cache/fastembed && chown -R app:app /app/.cache

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# Behind a reverse proxy, set FORWARDED_ALLOW_IPS to its address so client IPs and https are seen.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
