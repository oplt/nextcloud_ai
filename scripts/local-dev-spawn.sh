#!/usr/bin/env bash
# Spawn separate terminal windows/tabs for each local-dev service.
# Tries gnome-terminal, konsole, xfce4-terminal, alacritty, x-terminal-emulator.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

spawn_one() {
  local target="$1"
  local title="${2:-$1}"
  local inner
  inner="cd $(printf '%q' "$ROOT") && make $(printf '%q' "$target"); exec bash"

  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="$title" -- bash -lc "$inner" &
    return 0
  fi
  if command -v konsole >/dev/null 2>&1; then
    konsole -p "tabtitle=$title" -e bash -lc "$inner" &
    return 0
  fi
  if command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title "$title" -e "bash -lc $(printf '%q' "$inner")" &
    return 0
  fi
  if command -v alacritty >/dev/null 2>&1; then
    alacritty --title "$title" -e bash -lc "$inner" &
    return 0
  fi
  if command -v x-terminal-emulator >/dev/null 2>&1; then
    x-terminal-emulator -T "$title" -e bash -lc "$inner" &
    return 0
  fi

  echo "local-dev: no graphical terminal found." >&2
  echo "Install one of: gnome-terminal, konsole, xfce4-terminal, alacritty, or x-terminal-emulator (Debian alternatives)." >&2
  echo "Then re-run: make local-dev" >&2
  echo "Or run each in its own shell:" >&2
  echo "  make local-redis" >&2
  echo "  make local-ollama" >&2
  echo "  make local-backend" >&2
  echo "  make local-worker" >&2
  echo "  make local-scheduler" >&2
  echo "  make local-frontend" >&2
  exit 1
}

spawn_one local-redis "nc-ai redis"
spawn_one local-ollama "nc-ai ollama"
spawn_one local-backend "nc-ai backend"
spawn_one local-worker "nc-ai worker"
spawn_one local-scheduler "nc-ai scheduler"
spawn_one local-frontend "nc-ai frontend"

exit 0
