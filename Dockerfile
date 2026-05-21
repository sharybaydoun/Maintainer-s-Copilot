FROM python:3.12-slim AS builder

WORKDIR /build

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Minimal compiler tools only
RUN apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-runtime.txt .

# =========================================================
# Install CPU-only PyTorch FIRST
# =========================================================
RUN pip install \
    --trusted-host download.pytorch.org \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    --default-timeout=1000 \
    --retries 20 \
    --no-cache-dir \
    --prefix=/install \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.7.1+cpu

# =========================================================
# Install remaining runtime packages
# extra-index-url ensures ALL torch resolutions stay CPU-only
# =========================================================
RUN pip install \
    --default-timeout=1000 \
    --no-cache-dir \
    --prefix=/install \
    --no-deps \
    sentence-transformers==3.0.1 && \
    pip install \
    --default-timeout=1000 \
    --no-cache-dir \
    --prefix=/install \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements-runtime.txt

# =========================================================
# FINAL IMAGE
# =========================================================

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/home/copilot/.local/bin:$PATH"

# Runtime-only package
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 10001 copilot

# Python packages from builder
COPY --from=builder /install /usr/local

# App files
COPY README.md DECISIONS.md ./
COPY app ./app
COPY models ./models
COPY alembic ./alembic
COPY alembic.ini .
COPY eval_thresholds.yaml .
COPY reports ./reports
COPY evals ./evals
COPY scripts ./scripts
COPY docker/entrypoint.sh /entrypoint.sh

# Build RAG assets
RUN chmod +x /entrypoint.sh && \
    python scripts/build_rag_corpus.py && \
    python scripts/build_rag_index.py && \
    chown -R copilot:copilot /app

USER copilot

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -f http://127.0.0.1:8000/health/ready || exit 1

STOPSIGNAL SIGTERM

ENTRYPOINT ["/entrypoint.sh"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "30"]