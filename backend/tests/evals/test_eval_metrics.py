"""F21 — pure scoring-function unit tests, synthetic predictions only (no
LLM, no DB) per CLAUDE.md's 'mock all LLM calls in unit tests'."""

from app.evals.dataset import GoldenExample
from app.evals.metrics import (
    TriagePrediction,
    booking_completion_rate,
    emergency_recall,
    guardrail_catch_rate,
    triage_routing_accuracy,
)

_EXAMPLES = [
    GoldenExample(id="a", text="pait mein dard", language="roman_ur", expected_route="specialization", expected_specialization_slug="gastroenterologist"),
    GoldenExample(id="b", text="dant mein dard", language="roman_ur", expected_route="specialization", expected_specialization_slug="dentist"),
    GoldenExample(id="c", text="seene mein dard, saans nahi", language="roman_ur", expected_route="emergency"),
    GoldenExample(id="d", text="appointment book karni hai", language="roman_ur", expected_route="booking_direct"),
]


class TestTriageRoutingAccuracy:
    def test_all_correct_scores_1(self):
        predictions = [
            TriagePrediction("a", "specialization", "gastroenterologist"),
            TriagePrediction("b", "specialization", "dentist"),
            TriagePrediction("c", "emergency"),
            TriagePrediction("d", "booking_direct"),
        ]
        assert triage_routing_accuracy(_EXAMPLES, predictions) == 1.0

    def test_wrong_specialization_slug_counts_as_incorrect(self):
        predictions = [
            TriagePrediction("a", "specialization", "urologist"),  # wrong slug, right route
            TriagePrediction("b", "specialization", "dentist"),
            TriagePrediction("c", "emergency"),
            TriagePrediction("d", "booking_direct"),
        ]
        assert triage_routing_accuracy(_EXAMPLES, predictions) == 0.75

    def test_wrong_route_counts_as_incorrect_even_with_right_slug(self):
        predictions = [
            TriagePrediction("a", "booking_direct", "gastroenterologist"),
            TriagePrediction("b", "specialization", "dentist"),
            TriagePrediction("c", "emergency"),
            TriagePrediction("d", "booking_direct"),
        ]
        assert triage_routing_accuracy(_EXAMPLES, predictions) == 0.75

    def test_missing_prediction_counts_as_incorrect_not_crash(self):
        predictions = [TriagePrediction("a", "specialization", "gastroenterologist")]
        assert triage_routing_accuracy(_EXAMPLES, predictions) == 0.25

    def test_empty_examples_returns_zero(self):
        assert triage_routing_accuracy([], []) == 0.0


class TestEmergencyRecall:
    def test_all_emergencies_caught_is_perfect_recall(self):
        assert emergency_recall(_EXAMPLES, flagged_ids={"c"}) == 1.0

    def test_missed_emergency_reduces_recall(self):
        assert emergency_recall(_EXAMPLES, flagged_ids=set()) == 0.0

    def test_no_emergency_examples_is_vacuously_1(self):
        non_emergency = [e for e in _EXAMPLES if e.expected_route != "emergency"]
        assert emergency_recall(non_emergency, flagged_ids=set()) == 1.0

    def test_flagging_a_non_emergency_does_not_affect_recall(self):
        # False positives are a precision concern, not recall — this metric
        # is deliberately recall-only per spec.md's "missing one is worse".
        assert emergency_recall(_EXAMPLES, flagged_ids={"c", "a", "b", "d"}) == 1.0


class TestGuardrailCatchRate:
    def test_perfect_catch_rate(self):
        assert guardrail_catch_rate(should_flag=[True, True, False], did_flag=[True, True, False]) == 1.0

    def test_partial_catch_rate(self):
        assert guardrail_catch_rate(should_flag=[True, True, True, False], did_flag=[True, False, False, False]) == 1 / 3

    def test_mismatched_lengths_raise(self):
        import pytest

        with pytest.raises(ValueError):
            guardrail_catch_rate(should_flag=[True], did_flag=[True, False])

    def test_nothing_should_flag_is_vacuously_1(self):
        assert guardrail_catch_rate(should_flag=[False, False], did_flag=[True, False]) == 1.0


class TestBookingCompletionRate:
    def test_typical_funnel(self):
        assert booking_completion_rate(drafts=100, confirmed=42) == 0.42

    def test_zero_drafts_is_zero_not_divide_by_zero(self):
        assert booking_completion_rate(drafts=0, confirmed=0) == 0.0

    def test_full_conversion(self):
        assert booking_completion_rate(drafts=10, confirmed=10) == 1.0
