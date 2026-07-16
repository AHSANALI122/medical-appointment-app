"""Provider-agnostic LLM client shell.

Full agent wiring lands in F17+. For now this module only exposes enough to
satisfy the F0 acceptance criterion — `/health` can report which provider is
configured/primary and whether it has credentials — without importing the
Agents SDK or making network calls on every boot.
"""

from enum import StrEnum

from app.core.config import get_settings


class LLMProvider(StrEnum):
    GEMINI = "gemini"
    OPENAI = "openai"


class ProviderStatus(StrEnum):
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"


def _has_key(provider: LLMProvider) -> bool:
    settings = get_settings()
    if provider == LLMProvider.GEMINI:
        return bool(settings.gemini_api_key)
    if provider == LLMProvider.OPENAI:
        return bool(settings.openai_api_key)
    return False


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
