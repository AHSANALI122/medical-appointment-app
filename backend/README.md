# MedBook Backend

FastAPI backend for the MedBook medical appointment booking platform. See `/spec.md` and `/CLAUDE.md` at the repo root.

```bash
uv sync
docker compose up -d db          # local Postgres (see docker-compose.yml at repo root)
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

uv run pytest                    # all tests
uv run pytest -m "not live_llm"  # CI-safe
```
