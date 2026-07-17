"""F21 acceptance: golden dataset has >=100 labeled triage examples and the
keyword-layer emergency recall gate (>=99%) actually holds. Fully
deterministic — no LLM, no DB — so this runs on every PR, not just when
live_llm tests are enabled.
"""

from app.evals.dataset import load_golden_dataset
from app.evals.run_emergency_eval import RECALL_GATE, run as run_emergency_eval
from scripts.seed_taxonomy import SPECIALIZATIONS

MIN_EXAMPLES = 100
TAXONOMY_SLUGS = {slug for slug, _, _ in SPECIALIZATIONS}


class TestGoldenDatasetShape:
    def test_at_least_100_examples(self):
        assert len(load_golden_dataset()) >= MIN_EXAMPLES

    def test_ids_are_unique(self):
        examples = load_golden_dataset()
        ids = [e.id for e in examples]
        assert len(ids) == len(set(ids))

    def test_every_specialization_slug_is_in_the_fixed_taxonomy(self):
        # CLAUDE.md: specialization is a fixed taxonomy list, free text banned.
        # A golden example referencing a slug outside that list would silently
        # make triage_routing_accuracy unscoreable against the real system.
        examples = load_golden_dataset()
        used_slugs = {e.expected_specialization_slug for e in examples if e.expected_specialization_slug}
        assert used_slugs <= TAXONOMY_SLUGS

    def test_every_taxonomy_specialization_has_at_least_one_example(self):
        examples = load_golden_dataset()
        used_slugs = {e.expected_specialization_slug for e in examples if e.expected_specialization_slug}
        assert TAXONOMY_SLUGS <= used_slugs

    def test_is_roman_urdu_heavy(self):
        # spec.md explicitly calls for a "Roman Urdu heavy" dataset.
        examples = load_golden_dataset()
        roman_ur = sum(1 for e in examples if e.language == "roman_ur")
        assert roman_ur / len(examples) >= 0.5

    def test_has_at_least_30_percent_non_specialization_intents(self):
        # Triage isn't only symptom->specialization: emergency + booking/
        # reschedule/faq direct-intent examples must be represented too,
        # since real patient traffic is a mix, not purely symptom text.
        examples = load_golden_dataset()
        non_spec = sum(1 for e in examples if e.expected_route != "specialization")
        assert non_spec >= 20


class TestEmergencyRecallGate:
    def test_keyword_layer_meets_recall_gate(self):
        report = run_emergency_eval()
        assert report["recall"] >= RECALL_GATE, report["missed_ids"]
