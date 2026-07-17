"""F21 — LLM-as-judge for triage routing accuracy.

Why a judge instead of inspecting tool-call arguments directly: the Triage
Agent's actual decision surfaces as a natural-language handoff + reply, not
a single structured field, so scoring "did this route the patient toward
the right kind of doctor" is a judgment call, not an exact-match — which is
exactly what spec.md asks for with "LLM-as-judge evals: triage routing
accuracy". `calibrate_judge` is the other spec.md requirement this module
carries: "judge calibrated to >=85% human agreement before trusting scores."
Every live eval run should call `calibrate_judge` first and refuse to trust
its own accuracy number if calibration falls under CALIBRATION_GATE — a
judge that doesn't agree with humans on the easy, hand-labeled cases can't
be trusted on the hard ones either.
"""

import json
from pathlib import Path

from pydantic import BaseModel

from agents import Agent, RunConfig, Runner

from app.evals.dataset import GoldenExample

CALIBRATION_GATE = 0.85
_CALIBRATION_SET_PATH = Path(__file__).parent / "calibration_set.json"


class TriageJudgment(BaseModel):
    is_correct: bool
    reasoning: str


_judge_agent: Agent = Agent(
    name="Triage Judge",
    instructions=(
        "You evaluate whether a medical appointment assistant's reply correctly "
        "routed a patient toward the right kind of doctor for their described "
        "symptom. You are given the patient's message (possibly Roman Urdu, Urdu, "
        "or English), the specialization a human labeler considers correct, and "
        "the assistant's reply. Judge is_correct=true only if the reply's "
        "direction (which kind of doctor, or which next step) is clinically "
        "reasonable and consistent with the labeled specialization — a slightly "
        "different but still medically sensible specialization for an ambiguous "
        "symptom (e.g. general-physician vs gastroenterologist for vague stomach "
        "pain) may still be is_correct=true; a clearly wrong direction (e.g. "
        "routing chest pain to a dermatologist) is is_correct=false. You do not "
        "give medical advice yourself — you only judge routing correctness."
    ),
    output_type=TriageJudgment,
)


async def judge_triage_reply(*, example: GoldenExample, reply: str, model) -> TriageJudgment:
    label = example.expected_specialization_slug or example.expected_route
    prompt = (
        f"Patient message: {example.text!r}\n"
        f"Labeled-correct routing: {label}\n"
        f"Assistant reply: {reply!r}"
    )
    result = await Runner.run(_judge_agent, input=prompt, run_config=RunConfig(model=model))
    judgment = result.final_output
    return judgment if isinstance(judgment, TriageJudgment) else TriageJudgment(is_correct=False, reasoning="unparseable judge output")


def load_calibration_set() -> list[dict]:
    return json.loads(_CALIBRATION_SET_PATH.read_text(encoding="utf-8"))


async def calibrate_judge(model) -> float:
    """Runs the judge against the hand-labeled calibration set and returns
    the fraction where the judge's is_correct matches the human verdict.
    Callers must treat any eval run's accuracy number as untrustworthy if
    this falls below CALIBRATION_GATE (0.85, per spec.md)."""
    cases = load_calibration_set()
    if not cases:
        return 0.0

    agreements = 0
    for case in cases:
        example = GoldenExample(
            id=case["id"],
            text=case["text"],
            language=case["language"],
            expected_route=case["expected_route"],
            expected_specialization_slug=case.get("expected_specialization_slug"),
        )
        judgment = await judge_triage_reply(example=example, reply=case["candidate_reply"], model=model)
        if judgment.is_correct == case["human_verdict"]:
            agreements += 1

    return agreements / len(cases)
