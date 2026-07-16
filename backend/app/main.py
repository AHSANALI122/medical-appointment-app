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
from app.core.request_context import RequestIDMiddleware, get_request_id
from app.jobs.completion_sweep import sweep_completed_bookings
from app.jobs.expiry_sweep import sweep_expired_bookings
from app.jobs.followup_sweep import run_followup_sweep
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(_run_expiry_sweep, "interval", seconds=60, id="expiry_sweep")
    scheduler.add_job(_run_reminder_sweep, "interval", minutes=5, id="reminder_sweep")
    scheduler.add_job(_run_completion_sweep, "interval", minutes=15, id="completion_sweep")
    scheduler.add_job(_run_followup_sweep, "interval", hours=24, id="followup_sweep")
    scheduler.start()
    logger.info("app.startup", environment=settings.environment)
    yield
    scheduler.shutdown(wait=False)
    logger.info("app.shutdown")


app = FastAPI(title="MedBook API", version="0.1.0", lifespan=lifespan)

app.add_middleware(CSRFMiddleware)
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


@app.get("/health")
def health() -> dict:
    db_status = "ok"
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — health check must never raise
        db_status = f"error: {exc}"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
        "llm": get_llm_health(),
    }
