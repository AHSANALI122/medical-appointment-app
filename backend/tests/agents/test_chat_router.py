from tests.agents.fake_model import clean_turn


def _login_patient(client, patient_user):
    resp = client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})
    assert resp.status_code == 200


def test_create_session_and_send_message(client, patient_user, fake_llm):
    _login_patient(client, patient_user)
    fake_llm(clean_turn("Hi! How can I help you book an appointment today?"))

    session_resp = client.post("/api/v1/chat/sessions")
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    msg_resp = client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "hello"})
    assert msg_resp.status_code == 200
    body = msg_resp.json()
    assert body["emergency"] is False
    assert "book" in body["reply"].lower() or len(body["reply"]) > 0
    assert body["draft_booking"] is None


def test_get_session_is_idempotent(client, patient_user):
    _login_patient(client, patient_user)
    first = client.post("/api/v1/chat/sessions").json()
    second = client.post("/api/v1/chat/sessions").json()
    assert first["id"] == second["id"]


def test_message_history_persists_and_is_listable(client, patient_user, fake_llm):
    _login_patient(client, patient_user)
    fake_llm(clean_turn("Sure, tell me more."))

    session_id = client.post("/api/v1/chat/sessions").json()["id"]
    client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "pait mein thoda dard hai"})

    history_resp = client.get(f"/api/v1/chat/sessions/{session_id}/messages")
    assert history_resp.status_code == 200
    page = history_resp.json()
    assert page["total"] == 2
    assert page["items"][0]["role"] == "user"
    assert page["items"][1]["role"] == "assistant"


def test_emergency_keyword_short_circuits_without_llm(client, patient_user):
    _login_patient(client, patient_user)
    # Deliberately no fake_llm fixture installed — if the keyword fast-path
    # didn't short-circuit before any model call, this would raise trying
    # to build a real LitellmModel with no API key.
    session_id = client.post("/api/v1/chat/sessions").json()["id"]

    resp = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "mujhe seene mein dard ho raha hai"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["emergency"] is True
    assert "1122" in body["reply"]


def test_emergency_turn_does_not_taint_later_unrelated_turns(client, patient_user, fake_llm):
    """Regression test: a live-testing session found that the emergency
    guardrail was scanning the *entire* conversation history instead of
    just the current turn, so once an emergency phrase was ever mentioned,
    every later unrelated message in the same session kept tripping the
    guardrail forever. The keyword message itself never reaches the LLM
    (fast-path), but the follow-up message must go through normally."""
    _login_patient(client, patient_user)
    session_id = client.post("/api/v1/chat/sessions").json()["id"]

    emergency_resp = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "I have severe chest pain"}
    )
    assert emergency_resp.json()["emergency"] is True

    fake_llm(clean_turn("Sure, what kind of doctor are you looking for?"))
    followup_resp = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "Hi, can you tell me how booking works?"},
    )
    assert followup_resp.status_code == 200
    body = followup_resp.json()
    assert body["emergency"] is False
    assert body["reply"] == "Sure, what kind of doctor are you looking for?"


def test_cannot_access_another_users_chat_session(client_factory, session, patient_user):
    from tests.conftest import make_patient

    other_profile = make_patient(session, "chat-other@example.com")
    from app.services import agent_session_service

    other_session = agent_session_service.get_or_create_session(session, user_id=other_profile.user_id)

    owner_client = client_factory()
    _login_patient(owner_client, patient_user)

    resp = owner_client.get(f"/api/v1/chat/sessions/{other_session.id}/messages")
    assert resp.status_code == 404


def test_chat_rate_limit_enforced(client, patient_user, fake_llm):
    _login_patient(client, patient_user)
    session_id = client.post("/api/v1/chat/sessions").json()["id"]

    responses = []
    for _ in range(5):
        responses.extend(clean_turn("ok"))
    fake_llm(responses)
    for _ in range(5):
        resp = client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "hi again"})
        assert resp.status_code == 200

    blocked = client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "hi again"})
    assert blocked.status_code == 429
