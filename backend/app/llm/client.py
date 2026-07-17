"""Provider-agnostic LLM client.

F0 scope: report which provider is configured/primary without making network
calls (`get_llm_health`). F17 scope: the actual model objects the Agents SDK
runs against (`get_agent_model`), and a lightweight resilience wrapper
(`ResilientModelRouter`) satisfying the F22-style requirements CLAUDE.md's
Agent Architecture section calls out — exponential backoff on 429 (max 3),
a Gemini->OpenAI circuit breaker with a 60s cooldown, and a 30s run timeout
with a graceful fallback. This does not attempt the rest of F22 (frontend
error boundaries, job dead-letter queues) — those are out of scope here.
"""

import asyncio
import threading
import time
from enum import StrEnum

from agents import InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered
from openai import APIConnectionError, APITimeoutError, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.exceptions import LLMProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)

RUN_TIMEOUT_SECONDS = 30.0
CIRCUIT_BREAKER_COOLDOWN_SECONDS = 60.0
_RETRYABLE_EXCEPTIONS = (RateLimitError, APITimeoutError, APIConnectionError)
# Guardrail tripwires (F19: emergency detection, output scanning) are
# deliberate control-flow signals from the SDK, not provider-availability
# failures — they must never be treated as "provider down, try fallback."
# Doing so would risk masking a real emergency behind a generic connectivity
# error if the fallback provider then also failed for an unrelated reason.
_GUARDRAIL_EXCEPTIONS = (InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered)


class LLMProvider(StrEnum):
    GEMINI = "gemini"
    OPENAI = "openai"


class ProviderStatus(StrEnum):
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"


_PROVIDER_MODEL_STRINGS = {
    # "gemini-flash-latest" is Google's own recommended alias for the
    # current-generation flash model — a pinned version string (e.g.
    # gemini-2.5-flash) can 404 for new API keys once Google deprecates it
    # for new users while still serving existing callers, which is exactly
    # what happened here; the alias is the future-proof choice.
    LLMProvider.GEMINI: "gemini/gemini-flash-latest",
    LLMProvider.OPENAI: "openai/gpt-4o-mini",
}


def _has_key(provider: LLMProvider) -> bool:
    settings = get_settings()
    if provider == LLMProvider.GEMINI:
        return bool(settings.gemini_api_key)
    if provider == LLMProvider.OPENAI:
        return bool(settings.openai_api_key)
    return False


def _api_key_for(provider: LLMProvider) -> str:
    settings = get_settings()
    return settings.gemini_api_key if provider == LLMProvider.GEMINI else settings.openai_api_key


def get_llm_health() -> dict:
    settings = get_settings()
    primary = LLMProvider(settings.llm_primary)
    fallback = LLMProvider(settings.llm_fallback)

    return {
        "primary": primary.value,
        "primary_status": (
            ProviderStatus.CONFIGURED if _has_key(primary) else ProviderStatus.NOT_CONFIGURED
        ).value,
        "fallback": fallback.value,
        "fallback_status": (
            ProviderStatus.CONFIGURED if _has_key(fallback) else ProviderStatus.NOT_CONFIGURED
        ).value,
    }


def get_agent_model(provider: LLMProvider):
    """Builds the Agents SDK model object for a provider. Both Gemini and
    OpenAI go through the same `LitellmModel` wrapper (litellm model strings
    `gemini/...` / `openai/...`) — one code path for both providers is what
    makes the circuit breaker below simple: it never needs provider-specific
    branching, just "try this Model, try that Model"."""
    from agents.extensions.models.litellm_model import LitellmModel

    return LitellmModel(model=_PROVIDER_MODEL_STRINGS[provider], api_key=_api_key_for(provider))


def configure_tracing() -> None:
    """F21 — traces (sessions, handoffs, tool calls, tokens, latency) export
    to LangSmith when LANGSMITH_API_KEY is configured, via the Agents SDK's
    pluggable TracingProcessor hook: `set_trace_processors` replaces the
    default OpenAI-backend exporter outright, so there's one tracing
    destination, not two half-configured ones.

    Without a LangSmith key, tracing exports to the OpenAI backend by
    default, which requires an OpenAI API key even when the run itself uses
    Gemini. Without *any* key configured (dev/CI with no live keys), disable
    tracing entirely rather than let every run attempt — and fail — a
    network call. Mirrors the existing 'stub in dev' pattern
    (notification_service._send_email_stub)."""
    import agents

    settings = get_settings()
    if settings.langsmith_api_key:
        from langsmith import Client
        from langsmith.integrations.openai_agents_sdk import OpenAIAgentsTracingProcessor

        client = Client(api_key=settings.langsmith_api_key)
        agents.set_trace_processors(
            [OpenAIAgentsTracingProcessor(client=client, project_name=settings.langsmith_project)]
        )
    elif settings.openai_api_key:
        agents.set_tracing_export_api_key(settings.openai_api_key)
    else:
        agents.set_tracing_disabled(True)


class _CircuitBreaker:
    """Per-provider open/closed state with a fixed cooldown, in-process and
    global — the same shape as `InMemoryRateLimiter` in core/rate_limit.py."""

    def __init__(self) -> None:
        self._opened_at: dict[LLMProvider, float] = {}
        self._lock = threading.Lock()

    def is_open(self, provider: LLMProvider) -> bool:
        with self._lock:
            opened_at = self._opened_at.get(provider)
            if opened_at is None:
                return False
            if time.monotonic() - opened_at >= CIRCUIT_BREAKER_COOLDOWN_SECONDS:
                del self._opened_at[provider]
                return False
            return True

    def record_failure(self, provider: LLMProvider) -> None:
        with self._lock:
            self._opened_at[provider] = time.monotonic()

    def record_success(self, provider: LLMProvider) -> None:
        with self._lock:
            self._opened_at.pop(provider, None)

    def reset(self) -> None:
        """Test-only escape hatch — the breaker is process-global by design."""
        with self._lock:
            self._opened_at.clear()


_breaker = _CircuitBreaker()


def get_circuit_breaker() -> _CircuitBreaker:
    return _breaker


class ResilientModelRouter:
    """Runs an Agents SDK call against the primary provider with exponential
    backoff on 429/timeout/connection errors (max 3 attempts), falling back
    to the secondary provider (single attempt, no retry) if the primary is
    exhausted or its circuit breaker is open. Raises `LLMProviderError` only
    once both providers have failed — callers (runner.run_agent_turn) turn
    that into a graceful fallback message rather than a crash, so the manual
    booking flow is never affected by an LLM outage."""

    def __init__(self, *, primary: LLMProvider, fallback: LLMProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.last_provider_used: LLMProvider | None = None

    async def _run_once(self, provider: LLMProvider, run_fn):
        model = get_agent_model(provider)
        return await asyncio.wait_for(run_fn(model), timeout=RUN_TIMEOUT_SECONDS)

    async def run(self, run_fn):
        """`run_fn` is an async callable taking a `Model` and returning the
        `Runner.run(...)` coroutine result — kept generic so this module
        doesn't need to import agent-specific types."""
        breaker = get_circuit_breaker()

        if not breaker.is_open(self.primary):
            try:
                result = await self._retrying_primary(run_fn)
                breaker.record_success(self.primary)
                self.last_provider_used = self.primary
                return result
            except _GUARDRAIL_EXCEPTIONS:
                # Not a provider failure — the primary answered fine and a
                # guardrail correctly stopped the run. Propagate as-is.
                raise
            except Exception as exc:  # noqa: BLE001 — any other primary failure falls through to fallback
                logger.warning("llm.primary_failed", provider=self.primary.value, error=str(exc))
                breaker.record_failure(self.primary)
        else:
            logger.info("llm.primary_circuit_open", provider=self.primary.value)

        try:
            result = await self._run_once(self.fallback, run_fn)
            breaker.record_success(self.fallback)
            self.last_provider_used = self.fallback
            return result
        except _GUARDRAIL_EXCEPTIONS:
            raise
        except Exception as exc:  # noqa: BLE001 — both providers exhausted
            logger.error("llm.fallback_failed", provider=self.fallback.value, error=str(exc))
            breaker.record_failure(self.fallback)
            raise LLMProviderError("both LLM providers are currently unavailable") from exc

    async def _retrying_primary(self, run_fn):
        @retry(
            retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        )
        async def _attempt():
            return await self._run_once(self.primary, run_fn)

        return await _attempt()


def get_resilient_router() -> ResilientModelRouter:
    settings = get_settings()
    return ResilientModelRouter(
        primary=LLMProvider(settings.llm_primary),
        fallback=LLMProvider(settings.llm_fallback),
    )
