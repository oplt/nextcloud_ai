#!/usr/bin/env bash
# Write a compose file with host ports remapped so local :8000 does not collide.
# Must live under the repo root so relative build contexts resolve.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$ROOT_DIR/.phase1-compose.generated.yml}"
BACKEND_PORT="${PHASE1_BACKEND_PORT:-18000}"
NEXTCLOUD_PORT="${PHASE1_NEXTCLOUD_PORT:-18081}"
FRONTEND_PORT="${PHASE1_FRONTEND_PORT:-15173}"

python3 - "$ROOT_DIR/docker-compose.yml" "$OUT" "$BACKEND_PORT" "$NEXTCLOUD_PORT" "$FRONTEND_PORT" <<'PY'
from pathlib import Path
import re
import sys

src, dst, backend_port, nc_port, fe_port = sys.argv[1:6]
text = Path(src).read_text(encoding="utf-8")
text = text.replace('"8000:8000"', f'"{backend_port}:8000"')
text = text.replace('"8081:80"', f'"{nc_port}:80"')
text = text.replace('"5173:5173"', f'"{fe_port}:5173"')
text = text.replace("localhost:8081", f"localhost:{nc_port}")
text = text.replace("http://localhost:8000", f"http://localhost:{backend_port}")
text = text.replace(
    "OLLAMA_BOOTSTRAP_MODE: ensure",
    "OLLAMA_BOOTSTRAP_MODE: check",
)
# Smoke must use image-installed deps; bind-mounting ./backend hides /.venv.
text = re.sub(
    r"(?m)^([ \t]+)volumes:\n(?:\1[ \t]*- \./backend:/app/backend\n)+",
    "",
    text,
)
Path(dst).write_text(text, encoding="utf-8")
print(dst)
PY
