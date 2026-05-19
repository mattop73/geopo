#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Always (re)create backend/.env -> root .env so config picks up keys.
# The previous guard skipped relink when a stale/dangling symlink existed.
if [ -f .env ]; then
  ln -sf "$(pwd)/.env" backend/.env
else
  echo "[geopo] WARNING: no .env at repo root — backend will start without API keys"
fi

# Start backend
echo "[geopo] starting FastAPI backend on http://localhost:8000"
(cd backend && python -m uvicorn main:app --reload --port 8000) &
BACKEND_PID=$!

# Start frontend
echo "[geopo] starting Vite frontend on http://localhost:5173"
(cd frontend && npm run dev) &
FRONTEND_PID=$!

trap "echo '[geopo] stopping…'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT INT TERM

wait
