#!/bin/sh
# Container entrypoint: bring the schema up to date, then serve.
# Alembic upgrade is idempotent, so running it on every boot is safe; on
# Hugging Face Spaces there's no shell to run migrations manually.
set -e

alembic upgrade head

# Honor $PORT when the platform injects one (Render); default to 8000 so local
# docker-compose and other hosts keep working unchanged.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
