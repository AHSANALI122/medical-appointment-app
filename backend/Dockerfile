# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# MedBook backend — production multi-stage build.
#
# Stage 1 (builder): resolve and install dependencies into a self-contained
# virtualenv with uv. Deps are installed in their own layer *before* the app
# source is copied, so a code change doesn't bust the (slow) dependency layer.
#
# Stage 2 (runtime): a clean python:3.12-slim with only the venv + app source
# copied in — no uv, no build cache, no dev dependencies. Runs as non-root.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS builder

# uv binary from the official distroless image (pinned for reproducibility).
COPY --from=ghcr.io/astral-sh/uv:0.6.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# 1) Dependencies only — cached unless uv.lock / pyproject.toml change.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=README.md,target=README.md \
    uv sync --frozen --no-install-project --no-dev

# 2) App source + install the project itself (still no dev deps).
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# Non-root runtime user.
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

# Copy the resolved venv and app source from the builder. Both stages share the
# same base image, so the venv's interpreter path stays valid.
COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8000

# Container-level healthcheck hitting the app's own /health endpoint. The
# start-period covers `alembic upgrade head` running before uvicorn binds.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"]

# Run via `sh` so the entrypoint works regardless of the file's exec bit (Windows
# checkouts don't preserve it). start.sh migrates, then execs uvicorn.
CMD ["sh", "/app/start.sh"]
