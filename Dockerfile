# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the Geopo Dashboard.
#
# Stage 1 (frontend) builds the React/Vite SPA. Vite needs the Supabase
# URL + anon key at *build* time because they are baked into the JS
# bundle as `import.meta.env.VITE_*` constants. Railway will pass them as
# build args (see ARG declarations below).
#
# Stage 2 (runtime) installs the Python deps, copies the SPA build into
# /app/frontend/dist, and starts the FastAPI app with Gunicorn (uvicorn
# worker) on $PORT. The same process serves both /api/* JSON and the SPA.
# -----------------------------------------------------------------------------

# ---- Stage 1: build the SPA -------------------------------------------------
FROM node:20-alpine AS web

WORKDIR /web

# Supabase env vars are needed at build time so they end up in the static
# JS bundle. Railway injects them via --build-arg from the service env.
ARG VITE_SUPABASE_URL=""
ARG VITE_SUPABASE_ANON_KEY=""
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ ./
RUN npm run build


# ---- Stage 2: Python runtime -----------------------------------------------
FROM python:3.12-slim AS runtime

# psycopg2-binary ships its own libpq, but build-essential helps when wheels
# are missing for a transitive dep. Slim image keeps the layer small.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/ ./backend/

# Pull the built SPA from stage 1 into the location main.py expects.
COPY --from=web /web/dist/ ./frontend/dist/

# Railway sets $PORT at runtime; default to 8000 for local docker runs.
ENV PORT=8000
EXPOSE 8000

WORKDIR /app/backend

# Gunicorn + uvicorn worker is the standard production combo for FastAPI:
# Gunicorn handles process supervision + graceful reload, uvicorn does the
# actual ASGI work. One worker is enough for our IO-bound API + APScheduler
# (multiple workers would each spawn their own scheduler — bad).
CMD ["sh", "-c", "gunicorn main:app -k uvicorn.workers.UvicornWorker -w 1 -b 0.0.0.0:${PORT} --timeout 120"]
