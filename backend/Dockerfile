# Build context: my-agent/ (the monorepo root)
# docker build -f backend/Dockerfile .

# ── Stage 1: Frontend build ──────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json ./
RUN npm install

COPY frontend/ ./
# vite.config.ts sets outDir: '../backend/static'
# so output lands at /build/backend/static
RUN npm run build

# ── Stage 2: Backend runtime ─────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Install uv from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy lockfile + manifest first to maximise layer cache hits
COPY backend/pyproject.toml backend/uv.lock ./

# Install Python deps from the frozen lockfile (no internet needed after this)
RUN uv sync --frozen --no-dev

# Copy application source
COPY backend/ ./

# Copy compiled frontend assets from stage 1
COPY --from=frontend-builder /build/backend/static ./static

EXPOSE 7860

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
