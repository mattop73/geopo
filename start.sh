#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# The backend reads the root .env directly via backend/config.py.
if [ ! -f .env ]; then
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
