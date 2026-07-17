"""F21 — deterministic emergency-detection recall eval.

Scores only the keyword fast-path (`keyword_emergency_check`), not the LLM
classifier layer — and that's deliberate, not a shortcut: in production
(runner.py) the keyword layer is checked *before any LLM call is made at
all*, so its recall alone is exactly the "zero-latency catch" spec.md
describes. That makes this eval fully deterministic and free to run on
every PR (no live_llm marker needed) while still gating on a real,
production-meaningful number. `run_triage_eval.py` covers the full
keyword+classifier pipeline against a live model for the harder metric
(routing accuracy), which does need a live_llm marker.

    uv run python -m app.evals.run_emergency_eval
"""

import json
from pathlib import Path

from app.evals.dataset import load_golden_dataset
from app.evals.metrics import emergency_recall
from app.guardrails.emergency import keyword_emergency_check

RECALL_GATE = 0.99
REPORT_PATH = Path(__file__).parent / "reports" / "emergency_eval_report.json"


def run() -> dict:
    examples = load_golden_dataset()
    flagged_ids = {e.id for e in examples if keyword_emergency_check(e.text)}

    recall = emergency_recall(examples, flagged_ids)

    emergencies = [e for e in examples if e.is_emergency]
    missed = [e.id for e in emergencies if e.id not in flagged_ids]
    non_emergencies = [e for e in examples if not e.is_emergency]
    false_positives = [e.id for e in non_emergencies if e.id in flagged_ids]

    report = {
        "metric": "emergency_detection_recall_keyword_layer",
        "recall": recall,
        "gate": RECALL_GATE,
        "passed": recall >= RECALL_GATE,
        "emergency_examples": len(emergencies),
        "missed_ids": missed,
        "false_positive_ids": false_positives,
        "false_positive_rate": (len(false_positives) / len(non_emergencies)) if non_emergencies else 0.0,
    }
    return report


def write_report(report: dict, path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main() -> int:
    report = run()
    write_report(report)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
