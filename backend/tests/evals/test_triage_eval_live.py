"""F21 — full-pipeline live eval: runs the real Triage Agent (real LLM,
real emergency guardrail chain) against the golden dataset and scores it
against spec.md's CI deployment gates:

    triage routing accuracy >= 90%
    emergency-detection recall >= 99%  (full keyword+classifier pipeline)

Marked live_llm — excluded from the default `pytest -m "not live_llm"` CI
run (no API key needed there); a separate CI job runs this only when a
provider key is configured, per spec.md F21's "eval report artifact
attached to every agent-touching PR." The judge is calibrated first and the
run refuses to trust its own accuracy number if calibration falls under
CALIBRATION_GATE (spec.md: "judge calibrated to >=85% human agreement
before trusting scores").

    uv run pytest tests/evals/test_triage_eval_live.py -m live_llm
"""

import json
import os
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.agents.runner import run_agent_turn
from app.core.config import get_settings
from app.evals.dataset import load_golden_dataset
from app.evals.judge import CALIBRATION_GATE, calibrate_judge, judge_triage_reply
from app.evals.metrics import TriagePrediction, emergency_recall, triage_routing_accuracy
from app.llm.client import LLMProvider, get_agent_model
from app.models.taxonomy import SpecializationTaxonomy
from app.services import agent_session_service
from scripts.seed_taxonomy import SPECIALIZATIONS

pytestmark = pytest.mark.live_llm

TRIAGE_ACCURACY_GATE = 0.90
EMERGENCY_RECALL_GATE = 0.99
REPORT_PATH = Path(__file__).parent.parent.parent / "app" / "evals" / "reports" / "triage_eval_report.json"
# Full 122-example dataset against a live model has real cost/latency; cap
# via env var for a quick smoke run, default to the whole set for a real gate check.
SAMPLE_SIZE = int(os.environ.get("EVAL_SAMPLE_SIZE", "0")) or None


@pytest.fixture
def full_taxonomy(session: Session) -> dict[str, SpecializationTaxonomy]:
    by_slug = {}
    for slug, name_en, name_ur in SPECIALIZATIONS:
        existing = session.exec(
            select(SpecializationTaxonomy).where(SpecializationTaxonomy.slug == slug)
        ).first()
        row = existing or SpecializationTaxonomy(slug=slug, name_en=name_en, name_ur=name_ur)
        session.add(row)
        by_slug[slug] = row
    session.commit()
    for row in by_slug.values():
        session.refresh(row)
    return by_slug


async def test_full_pipeline_meets_ci_gates(session, patient_user, patient_profile, full_taxonomy):
    settings = get_settings()
    model = get_agent_model(LLMProvider(settings.llm_primary))

    calibration_score = await calibrate_judge(model)
    assert calibration_score >= CALIBRATION_GATE, (
        f"judge calibration {calibration_score:.0%} is below the {CALIBRATION_GATE:.0%} gate — "
        "the eval's accuracy number cannot be trusted until the judge (or calibration set) is fixed"
    )

    examples = load_golden_dataset()
    if SAMPLE_SIZE:
        examples = examples[:SAMPLE_SIZE]

    predictions: list[TriagePrediction] = []
    flagged_emergency_ids: set[str] = set()

    for example in examples:
        agent_session = agent_session_service.get_or_create_session(session, user_id=patient_user.id)
        agent_session.active_patient_profile_id = patient_profile.id

        result = await run_agent_turn(
            session, user=patient_user, agent_session=agent_session, user_message=example.text
        )

        if result.emergency:
            flagged_emergency_ids.add(example.id)
            predictions.append(TriagePrediction(example.id, "emergency"))
            continue

        if example.expected_route == "emergency":
            # Missed emergency — scored as incorrect routing AND counted in
            # the recall denominator via flagged_emergency_ids (not added).
            predictions.append(TriagePrediction(example.id, "not_emergency"))
            continue

        judgment = await judge_triage_reply(example=example, reply=result.reply, model=model)
        predicted_route = example.expected_route if judgment.is_correct else "incorrect"
        predicted_slug = example.expected_specialization_slug if judgment.is_correct else None
        predictions.append(TriagePrediction(example.id, predicted_route, predicted_slug))

    accuracy = triage_routing_accuracy(examples, predictions)
    recall = emergency_recall(examples, flagged_emergency_ids)

    report = {
        "triage_routing_accuracy": accuracy,
        "triage_accuracy_gate": TRIAGE_ACCURACY_GATE,
        "emergency_recall_full_pipeline": recall,
        "emergency_recall_gate": EMERGENCY_RECALL_GATE,
        "judge_calibration_score": calibration_score,
        "sample_size": len(examples),
        "passed": accuracy >= TRIAGE_ACCURACY_GATE and recall >= EMERGENCY_RECALL_GATE,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    assert recall >= EMERGENCY_RECALL_GATE, report
    assert accuracy >= TRIAGE_ACCURACY_GATE, report
