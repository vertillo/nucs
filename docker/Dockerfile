# syntax=docker/dockerfile:1
# nucs — single multi-stage image (spec 12.1): static frontend (Vite) + Python runtime.
# Multi-arch by design: no architecture-specific package is installed, every machine
# builds locally for its own architecture (`docker compose build`; arm64 on macOS,
# amd64 on the mini PC). No registry involved.

# --- Stage fe: build the static frontend (Vite/React/TS) ---
FROM node:20-alpine AS fe
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Stage runtime: Python app serving the API + the built frontend ---
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# tini as PID 1: reaps zombies and forwards signals to uvicorn.
# Version pinned by the base image's Debian suite (trixie, 0.19.0-3+b7 on arm64);
# the binNMU suffix is architecture-specific, so the suite pin is the
# reproducible version for every arch built from this base image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY backend/ /app/backend
COPY --from=fe /frontend/dist /app/static

# Non-root runtime user (uid 1000), owner of /app and of the DATA_DIR mount point.
# No home directory: the container runs on a read-only rootfs (only /tmp and the
# /data volume are writable), so HOME points at the tmpfs.
RUN useradd --uid 1000 --no-create-home app \
    && mkdir -p /app /data \
    && chown -R app:app /app /data

USER app

ENV HOME=/tmp \
    DATA_DIR=/data \
    COVERS_DIR=/data/covers \
    FRONTEND_DIST=/app/static

WORKDIR /app/backend

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health')"

ENTRYPOINT ["/usr/bin/tini", "--"]
# --proxy-headers: honour X-Forwarded-* only from TRUSTED_PROXY_CIDRS peers (spec 5.6).
# --no-server-header: never leak the `server: uvicorn` header (recorded fix, phase 11).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--no-server-header", "--workers", "1"]
