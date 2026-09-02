"""F21 — tracing destination selection is a pure function of which keys are
configured; F0/F22 — get_llm_health reports provider config status without
making a network call. No real LangSmith/OpenAI network calls in any of
these (mocked per CLAUDE.md's 'mock all LLM calls in unit tests')."""

from dataclasses import dataclass

import pytest

import app.llm.client as llm_client
from app.core.exceptions import LLMProviderError


@dataclass
class _FakeSettings:
    langsmith_api_key: str = ""
    langsmith_project: str = "medbook"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    llm_primary: str = "gemini"
    llm_fallback: str = "openai"


class TestConfigureTracing:
    def test_langsmith_key_wires_langsmith_processor(self, monkeypatch):
        monkeypatch.setattr(llm_client, "get_settings", lambda: _FakeSettings(langsmith_api_key="ls-key"))

        captured = {}
        monkeypatch.setattr("langsmith.Client", lambda api_key: f"client-for-{api_key}")
        monkeypatch.setattr(
            "agents.set_trace_processors", lambda processors: captured.update(processors=processors)
        )

        llm_client.configure_tracing()

        assert "processors" in captured
        assert len(captured["processors"]) == 1

    def test_no_langsmith_falls_back_to_openai_export(self, monkeypatch):
        monkeypatch.setattr(llm_client, "get_settings", lambda: _FakeSettings(openai_api_key="oai-key"))

        captured = {}
        monkeypatch.setattr("agents.set_tracing_export_api_key", lambda key: captured.update(key=key))

        llm_client.configure_tracing()

        assert captured["key"] == "oai-key"

    def test_no_keys_disables_tracing(self, monkeypatch):
        monkeypatch.setattr(llm_client, "get_settings", lambda: _FakeSettings())

        captured = {}
        monkeypatch.setattr("agents.set_tracing_disabled", lambda flag: captured.update(disabled=flag))

        llm_client.configure_tracing()

        assert captured["disabled"] is True


class TestGetLLMHealth:
    def test_reports_configured_and_not_configured(self, monkeypatch):
        monkeypatch.setattr(
            llm_client, "get_settings", lambda: _FakeSettings(gemini_api_key="gk", openai_api_key="")
        )

        health = llm_client.get_llm_health()

        assert health["primary"] == "gemini"
        assert health["primary_status"] == "configured"
        assert health["fallback"] == "openai"
        assert health["fallback_status"] == "not_configured"


class TestUnconfiguredProvidersAreNotCalled:
    """A provider with no API key is a misconfiguration, not an outage. Calling
    it anyway spends a round trip to have litellm answer 'Missing credentials',
    which then opens that provider's breaker and makes an unset env var read as
    a provider incident in the logs."""

    async def test_unconfigured_fallback_is_not_called_when_primary_fails(self, monkeypatch):
        monkeypatch.setattr(
            llm_client, "get_settings", lambda: _FakeSettings(gemini_api_key="gk", openai_api_key="")
        )
        llm_client.get_circuit_breaker().reset()

        called: list[str] = []

        def _fake_model(provider):
            called.append(provider.value)
            raise RuntimeError("primary is down")

        monkeypatch.setattr(llm_client, "get_agent_model", _fake_model)

        with pytest.raises(LLMProviderError):
            await llm_client.get_resilient_router().run(lambda model: model)

        assert "openai" not in called
        assert called == ["gemini"]  # tried once, then stopped — no keyless fallback attempt
        llm_client.get_circuit_breaker().reset()

    async def test_unconfigured_primary_is_skipped_in_favour_of_the_fallback(self, monkeypatch):
        monkeypatch.setattr(
            llm_client, "get_settings", lambda: _FakeSettings(gemini_api_key="", openai_api_key="ok")
        )
        llm_client.get_circuit_breaker().reset()

        called: list[str] = []

        def _fake_model(provider):
            called.append(provider.value)
            return "model"

        monkeypatch.setattr(llm_client, "get_agent_model", _fake_model)

        async def _run_fn(model):
            return f"answered-by-{model}"

        result = await llm_client.get_resilient_router().run(_run_fn)

        assert result == "answered-by-model"
        assert called == ["openai"]
        llm_client.get_circuit_breaker().reset()
