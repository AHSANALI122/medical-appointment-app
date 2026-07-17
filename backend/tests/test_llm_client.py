"""F21 — tracing destination selection is a pure function of which keys are
configured; F0/F22 — get_llm_health reports provider config status without
making a network call. No real LangSmith/OpenAI network calls in any of
these (mocked per CLAUDE.md's 'mock all LLM calls in unit tests')."""

from dataclasses import dataclass

import app.llm.client as llm_client


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
