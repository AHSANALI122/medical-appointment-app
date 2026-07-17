"""F21 — golden dataset loader. `golden_dataset.json` holds >=100 labeled
triage examples (Roman Urdu heavy, per spec.md), each labeled with the route
a correct triage decision should take: `specialization` (symptom text ->
one of the fixed taxonomy slugs), `emergency` (should trip the guardrail,
never reach routing), or a direct intent (`booking_direct`, `reschedule`,
`faq`) that bypasses symptom-based specialization routing entirely.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

_DATASET_PATH = Path(__file__).parent / "golden_dataset.json"

TriageRoute = Literal["specialization", "emergency", "booking_direct", "reschedule", "faq"]


class GoldenExample(BaseModel):
    id: str
    text: str
    language: Literal["en", "ur", "roman_ur"]
    expected_route: TriageRoute
    expected_specialization_slug: str | None = None

    @property
    def is_emergency(self) -> bool:
        return self.expected_route == "emergency"


def load_golden_dataset() -> list[GoldenExample]:
    raw = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    return [GoldenExample.model_validate(row) for row in raw]
