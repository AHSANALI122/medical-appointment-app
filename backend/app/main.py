from contextlib import asynccontextmanager

import sentry_sdk
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import Session

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.csrf import CSRFMiddleware
from app.core.db import engine
from app.core.exceptions import MedBookError
from app.core.logging import configure_logging, get_logger
from app.core.metrics import MetricsMiddleware
from app.core.request_context import RequestIDMiddleware, get_request_id
from app.jobs.completion_sweep import sweep_completed_bookings
from app.jobs.expiry_sweep import sweep_expired_bookings
from app.jobs.followup_sweep import run_followup_sweep
from app.jobs.purge_sweep import sweep_purgeable_accounts
from app.jobs.reminders import send_due_reminders
from app.llm.client import configure_tracing, get_llm_health

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, traces_sample_rate=0.1)

configure_tracing()

scheduler = AsyncIOScheduler()


def _run_expiry_sweep() -> None:
    with Session(engine) as session:
        count = sweep_expired_bookings(session)
        if count:
            logger.info("expiry_sweep.completed", expired_count=count)


def _run_reminder_sweep() -> None:
    with Session(engine) as session:
        count = send_due_reminders(session)
        if count:
            logger.info("reminder_sweep.completed", sent_count=count)


def _run_completion_sweep() -> None:
    with Session(engine) as session:
        count = sweep_completed_bookings(session)
        if count:
            logger.info("completion_sweep.completed", completed_count=count)


def _run_followup_sweep() -> None:
    with Session(engine) as session:
        run_followup_sweep(session)


def _run_purge_sweep() -> None:
    with Session(engine) as session:
        count = sweep_purgeable_accounts(session)
        if count:
            logger.info("purge_sweep.completed", purged_count=count)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(_run_expiry_sweep, "interval", seconds=60, id="expiry_sweep")
    scheduler.add_job(_run_reminder_sweep, "interval", minutes=5, id="reminder_sweep")
    scheduler.add_job(_run_completion_sweep, "interval", minutes=15, id="completion_sweep")
    scheduler.add_job(_run_followup_sweep, "interval", hours=24, id="followup_sweep")
    # F27: the purge deadline is a DB column, so the exact tick time doesn't
    # matter — daily is enough for a 30-day window, and a missed tick (deploy,
    # restart) just purges on the next one rather than losing the account.
    scheduler.add_job(_run_purge_sweep, "interval", hours=24, id="purge_sweep")
    scheduler.start()
    logger.info("app.startup", environment=settings.environment)
    yield

    # F29 graceful shutdown. Uvicorn drains in-flight *requests* before it
    # runs this teardown, so what's left is the scheduler.
    #
    # `wait=False` is deliberate, not a shortcut: every sweep is idempotent
    # and driven off DB deadline columns (CLAUDE.md rule 4), so abandoning a
    # tick mid-flight loses nothing — the uncommitted transaction rolls back
    # and the next tick after restart picks the same rows up. Waiting instead
    # would let a slow query hold the deploy open until the platform SIGKILLs
    # us, which is strictly worse: that kills in-flight requests too.
    scheduler.shutdown(wait=False)
    logger.info("app.shutdown")


# F29 — OpenAPI docs are public in dev, auth-gated in production. In prod the
# built-in routes are switched off and re-served below behind `require_admin`;
# leaving them on and "hiding" them would just be security by obscurity, since
# /openapi.json enumerates every route and schema we have.
_docs_are_public = not settings.is_production

app = FastAPI(
    title="MedBook API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_are_public else None,
    redoc_url="/redoc" if _docs_are_public else None,
    openapi_url="/openapi.json" if _docs_are_public else None,
)


if not _docs_are_public:
    from fastapi import Depends
    from fastapi.openapi.docs import get_swagger_ui_html

    from app.api.deps import require_admin

    _GATED_OPENAPI_URL = "/openapi.json"

    @app.get(_GATED_OPENAPI_URL, include_in_schema=False, dependencies=[Depends(require_admin)])
    def gated_openapi() -> dict:
        return app.openapi()

    @app.get("/docs", include_in_schema=False, dependencies=[Depends(require_admin)])
    def gated_docs():
        # Swagger UI fetches the spec from the browser, carrying the admin's
        # cookies — so the gate on /openapi.json above holds for it too.
        return get_swagger_ui_html(openapi_url=_GATED_OPENAPI_URL, title="MedBook API — docs")

app.add_middleware(CSRFMiddleware)
# Ordering note: `add_middleware` puts the most recently added outermost, so
# the effective chain is CORS -> RequestID -> Metrics -> CSRF -> route.
# Metrics sits inside RequestID (its records are correlatable to a
# request_id) but outside CSRF and routing, so a rejected-by-CSRF request
# still shows up in latency rather than silently vanishing.
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MedBookError)
async def medbook_error_handler(request: Request, exc: MedBookError) -> JSONResponse:
    request_id = get_request_id(request)
    logger.warning(
        "request.error",
        error_code=exc.error_code,
        message=exc.message,
        request_id=request_id,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message, "request_id": request_id},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = get_request_id(request)
    logger.error(
        "request.unhandled_error",
        error=str(exc),
        request_id=request_id,
        path=request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "internal_error",
            "message": "an unexpected error occurred",
            "request_id": request_id,
        },
    )


app.include_router(api_router)


@app.get("/", include_in_schema=False)
def root() -> dict:
    """Landing payload for the API root.

    The backend serves JSON under `/api/v1`, not web pages — the app UI lives
    on the frontend (FRONTEND_ORIGIN). Hitting the bare host used to return a
    bald `{"detail":"Not Found"}`, which reads like a bug; this points callers
    at the real entry points instead.
    """
    return {
        "service": "MedBook API",
        "version": app.version,
        "status": "ok",
        "app_url": settings.frontend_origin,
        "docs": "/docs" if _docs_are_public else "disabled_in_production",
        "health": "/health",
        "api_base": "/api/v1",
    }


@app.get("/health")
def health() -> JSONResponse:
    """Public (unauthenticated) — this is what the external uptime monitor
    polls; see docs/observability.md.

    Returns 503 when the DB is unreachable, not 200-with-a-sad-body: a
    monitor configured the obvious way checks the status code, and a health
    check that answers 200 during a total database outage is worse than no
    health check at all. The body still carries the detail for humans.

    LLM provider config is reported but deliberately does NOT affect the
    status code — agents being down is a degraded *feature*, while the
    manual booking flow (the thing that must never die) doesn't touch the
    LLM at all. Paging someone at 3am because a free tier lapsed would be
    exactly the wrong signal.
    """
    db_status = "ok"
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — health check must never raise
        db_status = f"error: {exc}"
        logger.error("health.db_unreachable", error=str(exc))

    healthy = db_status == "ok"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "db": db_status,
            "llm": get_llm_health(),
        },
    )
