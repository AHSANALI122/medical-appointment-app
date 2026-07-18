#!/bin/sh
# Container entrypoint: bring the schema up to date, then serve.
# Alembic upgrade is idempotent, so running it on every boot is safe; on
# Hugging Face Spaces there's no shell to run migrations manually.
set -e

alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
