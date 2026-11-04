#!/usr/bin/env bash
# Starts the backend (uvicorn, port 8000) and the Flutter web frontend (Chrome).
# Usage (from the repository root):   ./scripts/start.sh
# macOS / Linux / Git Bash. On Windows PowerShell use scripts/start.ps1.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY="$ROOT/backend/.venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then
  echo "Backend environment not found. Create it once with:"
  echo "  python3 -m venv backend/.venv"
  echo "  backend/.venv/bin/python -m pip install -r backend/requirements.txt"
  exit 1
fi
command -v flutter >/dev/null || { echo "Flutter is not on the PATH."; exit 1; }

BACKEND_URL="http://localhost:$BACKEND_PORT"
echo "Starting backend on $BACKEND_URL ..."
"$PY" -m uvicorn app.main:create_app --factory --app-dir "$ROOT/backend" \
  --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!
trap 'echo "Stopping backend ..."; kill $BACKEND_PID 2>/dev/null || true' EXIT

cd "$ROOT/frontend"
flutter run -d chrome --web-port "$WEB_PORT" --dart-define=BACKEND_URL="$BACKEND_URL"
