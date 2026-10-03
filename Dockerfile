# Multi-stage build: Next.js static export -> served by the FastAPI backend.
# One image, one service. Works on Render, Railway, Fly, or any Docker host.
#
#   Stage 1 (node)   builds frontend/ into a static export (frontend/out)
#   Stage 2 (python) installs Playwright + Chromium and serves the export
#
# Render/Railway/Fly all inject PORT; the CMD honours it.

# Base tags are pinned to the Debian release on purpose. A floating
# `python:3.11-slim` silently moved from bookworm to trixie, which broke
# `playwright install --with-deps` (it fell back to ubuntu20.04 packages and
# failed on ttf-unifont). Pinning makes the build reproducible.
# ---------------------------------------------------------------- stage 1
FROM node:22-bookworm-slim AS frontend

WORKDIR /build

# Copy manifests first so the dependency layer caches across source edits.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------- stage 2
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HEADLESS=true \
    VIDEO_DIR=/tmp/videos \
    UPLOAD_DIR=/tmp/uploads \
    DEBUG_DIR=/tmp/debug \
    STATIC_DIR=/app/static \
    DB_PATH=/tmp/accounts.db \
    MAX_WORKERS=1

WORKDIR /app

# ffmpeg gives us ffprobe for the 4-30s duration check. The rest of the OS
# libraries Chromium needs are installed by `playwright install --with-deps`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ ./

# The built frontend, served by FastAPI at "/" (STATIC_DIR above).
COPY --from=frontend /build/out ./static

# Render, Railway and Fly all set PORT. Default to 8000 locally.
# --workers 1 is required: the generation workers are asyncio tasks inside the
# single process, and each one drives its own Chromium.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-keep-alive 75"]
