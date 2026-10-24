#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: Python 3 is required but was not found in PATH." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Error: Node.js and npm are required but npm was not found in PATH." >&2
  exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Creating the backend virtual environment..."
  python3 -m venv "$BACKEND_DIR/.venv"
fi

if ! "$VENV_PYTHON" -c "import fastapi, uvicorn, httpx, pydantic" >/dev/null 2>&1; then
  echo "Installing backend dependencies..."
  "$VENV_PYTHON" -m pip install -r "$BACKEND_DIR/requirements.txt"
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  (cd "$FRONTEND_DIR" && npm install)
fi

backend_pid=""
frontend_pid=""
cleaned_up=0

cleanup() {
  if (( cleaned_up )); then
    return
  fi
  cleaned_up=1

  for pid in "$backend_pid" "$frontend_pid"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done

  for pid in "$backend_pid" "$frontend_pid"; do
    if [[ -n "$pid" ]]; then
      wait "$pid" >/dev/null 2>&1 || true
    fi
  done
}

handle_signal() {
  cleanup
  exit 130
}

trap cleanup EXIT
trap handle_signal INT TERM

(
  cd "$BACKEND_DIR"
  exec "$VENV_PYTHON" -m uvicorn app.main:app --reload --port 8000
) &
backend_pid=$!

(
  cd "$FRONTEND_DIR"
  exec npm run dev
) &
frontend_pid=$!

echo
echo "ReadIt is starting:"
echo "  App:     http://localhost:5173"
echo "  Backend: http://localhost:8000"
echo "Press Ctrl+C to stop both processes."
echo

exit_code=0
while kill -0 "$backend_pid" >/dev/null 2>&1 && kill -0 "$frontend_pid" >/dev/null 2>&1; do
  sleep 1
done

if ! kill -0 "$backend_pid" >/dev/null 2>&1; then
  wait "$backend_pid" || exit_code=$?
else
  wait "$frontend_pid" || exit_code=$?
fi

exit "$exit_code"
