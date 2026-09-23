#!/usr/bin/env bash
# Phase 3: disposable Ollama + live embedding compatibility smoke.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

OLLAMA_NAME="${PHASE3_OLLAMA_NAME:-phase3-ollama}"
OLLAMA_PORT="${PHASE3_OLLAMA_PORT:-11435}"
MODEL="${PHASE3_EMBED_MODEL:-bge-m3:latest}"
KEEP_INFRA="${PHASE3_KEEP_INFRA:-0}"

cleanup() {
  if [[ "$KEEP_INFRA" == "1" ]]; then
    echo "PHASE3_KEEP_INFRA=1 — leaving ${OLLAMA_NAME}"
    return
  fi
  docker rm -f "$OLLAMA_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Starting disposable Ollama on :${OLLAMA_PORT}"
docker rm -f "$OLLAMA_NAME" >/dev/null 2>&1 || true
docker run -d --name "$OLLAMA_NAME" -p "${OLLAMA_PORT}:11434" ollama/ollama:latest >/dev/null

ready=0
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${OLLAMA_PORT}/api/tags" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "Ollama failed to become ready" >&2
  docker logs --tail=50 "$OLLAMA_NAME" >&2 || true
  exit 1
fi

export OLLAMA_BASE_URL="http://127.0.0.1:${OLLAMA_PORT}"
export OLLAMA_EMBEDDING_MODEL="$MODEL"
export APP_ENV=test
export RAG_TRUE_RERANK_ENABLED=false
export EMBEDDING_PROVIDER=ollama
export PYTHONPATH="$ROOT_DIR"
# Reuse local secrets defaults from backend/.env via Settings env_file; override dim/provider only.

echo "==> Pull + embed smoke (model=${MODEL})"
backend/.venv/bin/python -m backend.scripts.phase3_embed_smoke \
  --base-url "$OLLAMA_BASE_URL" \
  --model "$MODEL" \
  --pull

echo "==> Phase 3 embed smoke OK"
