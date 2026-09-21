FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV HF_HOME=/var/cache/huggingface
ENV TRANSFORMERS_CACHE=/var/cache/huggingface/transformers

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/cache/huggingface/transformers

COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv

COPY backend/pyproject.toml backend/uv.lock /app/backend/
COPY backend /app/backend

# Install locked dependencies including the enabled rerank extra.
# Project layout is imported as `backend.*` via PYTHONPATH=/app (not a nested package).
WORKDIR /app/backend
RUN uv sync --frozen --extra rerank --no-dev --no-install-project

ENV PATH="/app/backend/.venv/bin:${PATH}"
WORKDIR /app

# Optional model bake: BUILD_RERANK_MODEL=1 downloads weights at image build time.
ARG BUILD_RERANK_MODEL=0
ARG RAG_TRUE_RERANK_MODEL=BAAI/bge-reranker-v2-m3
RUN if [ "$BUILD_RERANK_MODEL" = "1" ]; then \
      python -c "from sentence_transformers import CrossEncoder; CrossEncoder('${RAG_TRUE_RERANK_MODEL}', max_length=512)"; \
    fi

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
