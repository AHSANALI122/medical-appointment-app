"""F26 — /health is what the external uptime monitor polls
(docs/observability.md), so its status code is a contract, not a detail."""


class TestHealth:
    def test_healthy_returns_200_and_ok(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["db"] == "ok"
        assert "llm" in body

    def test_db_unreachable_returns_503_so_the_monitor_actually_alerts(self, client, monkeypatch):
        import app.main as main

        class _DeadEngine:
            def connect(self, *args, **kwargs):
                raise RuntimeError("connection refused")

            # Session(engine) touches these during construction/exec.
            def __getattr__(self, name):
                raise RuntimeError("connection refused")

        monkeypatch.setattr(main, "engine", _DeadEngine())

        response = client.get("/health")

        assert response.status_code == 503
        assert response.json()["status"] == "degraded"

    def test_health_needs_no_authentication(self, client_factory):
        assert client_factory().get("/health").status_code == 200
