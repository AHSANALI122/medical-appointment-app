"""F22 chaos suite acceptance criterion: LLM provider killed mid-run, and a
network/DB drop at confirm, must both produce zero data corruption — the
manual booking flow keeps working, and a failed transaction never leaves a
booking in a half-transitioned state.

Concurrent same-slot booking (the third chaos scenario in spec.md F22) is
already covered by test_concurrency.py's 10-parallel-bookings test; not
duplicated here.
"""

from datetime import timedelta

import pytest
from openai import APIConnectionError
from sqlmodel import Session

from app.core.exceptions import LLMProviderError
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.enums import BookingStatus
from app.services import booking_service
from app.services.state_machine import BookingStateMachine


def _api_connection_error() -> APIConnectionError:
    import httpx

    return APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))


class TestLLMProviderKilledMidRun:
    async def test_both_providers_down_returns_graceful_message_not_exception(
        self, monkeypatch, session, patient_user, patient_profile
    ):
        import app.llm.client as llm_client
        from app.agents.runner import LLM_UNAVAILABLE_MESSAGE, run_agent_turn
        from app.services import agent_session_service

        class _DeadModel:
            async def get_response(self, *args, **kwargs):
                raise _api_connection_error()

        monkeypatch.setattr(llm_client, "get_agent_model", lambda provider: _DeadModel())
        llm_client.get_circuit_breaker().reset()

        agent_session = agent_session_service.get_or_create_session(session, user_id=patient_user.id)
        agent_session.active_patient_profile_id = patient_profile.id

        result = await run_agent_turn(
            session, user=patient_user, agent_session=agent_session, user_message="mujhe doctor chahiye"
        )

        assert result.reply == LLM_UNAVAILABLE_MESSAGE
        assert result.emergency is False
        assert result.draft_booking_id is None

        # Zero data corruption: the user's turn and the graceful assistant
        # reply are both persisted — no half-written exchange.
        messages, _ = agent_session_service.list_messages(session, agent_session=agent_session, offset=0, limit=10)
        contents = [m.content for m in messages]
        assert "mujhe doctor chahiye" in contents
        assert LLM_UNAVAILABLE_MESSAGE in contents

        llm_client.get_circuit_breaker().reset()

    async def test_manual_booking_flow_unaffected_while_llm_is_down(
        self, monkeypatch, session, patient_profile, verified_doctor, clinic_location
    ):
        import app.llm.client as llm_client

        class _DeadModel:
            async def get_response(self, *args, **kwargs):
                raise _api_connection_error()

        monkeypatch.setattr(llm_client, "get_agent_model", lambda provider: _DeadModel())
        llm_client.get_circuit_breaker().reset()

        with pytest.raises(LLMProviderError):
            await llm_client.get_resilient_router().run(lambda model: model.get_response())

        # The manual (non-agent) booking path never touches the LLM client at
        # all — it must succeed exactly as if nothing were wrong.
        start = now_utc() + timedelta(minutes=60)
        end = start + timedelta(minutes=30)
        machine = BookingStateMachine(session)
        booking = machine.create_draft(
            patient_profile_id=patient_profile.id,
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            start_time_utc=start,
            end_time_utc=end,
            fee_charged=verified_doctor.consultation_fee,
            address_snapshot="123 Main Blvd, Lahore",
        )
        assert booking.status == BookingStatus.DRAFT

        llm_client.get_circuit_breaker().reset()


class TestNetworkDropAtConfirm:
    def test_failed_commit_leaves_booking_still_draft(
        self, test_engine, session, patient_profile, verified_doctor, clinic_location, monkeypatch
    ):
        start = now_utc() + timedelta(minutes=60)
        end = start + timedelta(minutes=30)
        machine = BookingStateMachine(session)
        booking = machine.create_draft(
            patient_profile_id=patient_profile.id,
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            start_time_utc=start,
            end_time_utc=end,
            fee_charged=verified_doctor.consultation_fee,
            address_snapshot="123 Main Blvd, Lahore",
        )
        booking_id = booking.id

        real_commit = Session.commit
        call_count = {"n": 0}

        def _flaky_commit(self_session):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First commit attempt is the confirm() transition — simulate
                # the connection dropping before the server ACK reaches the client.
                raise ConnectionError("simulated network drop")
            return real_commit(self_session)

        monkeypatch.setattr(Session, "commit", _flaky_commit)

        with pytest.raises(ConnectionError):
            booking_service.confirm_booking(session, booking_id=booking_id, patient_profile=patient_profile)

        session.rollback()
        monkeypatch.setattr(Session, "commit", real_commit)

        # A fresh connection/session — standing in for "the next request" —
        # must see the booking exactly as it was before the dropped confirm,
        # never a half-applied pending transition.
        with Session(test_engine) as fresh_session:
            reloaded = fresh_session.get(Booking, booking_id)
            assert reloaded.status == BookingStatus.DRAFT

        # And the flow is not permanently broken — retrying (the client's
        # natural response to a dropped request) succeeds cleanly.
        confirmed = booking_service.confirm_booking(session, booking_id=booking_id, patient_profile=patient_profile)
        assert confirmed.status == BookingStatus.PENDING
