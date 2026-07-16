"""Seeds the fixed specialization taxonomy (F2). Idempotent — safe to re-run.

    uv run python scripts/seed_taxonomy.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.core.db import engine  # noqa: E402
from app.models.taxonomy import SpecializationTaxonomy  # noqa: E402

SPECIALIZATIONS = [
    ("general-physician", "General Physician", "جنرل فزیشن"),
    ("cardiologist", "Cardiologist", "امراض قلب کے ماہر"),
    ("dermatologist", "Dermatologist", "جلدی امراض کے ماہر"),
    ("dentist", "Dentist", "دانتوں کے ڈاکٹر"),
    ("gynecologist", "Gynecologist", "امراض نسواں کے ماہر"),
    ("pediatrician", "Pediatrician", "اطفال کے ماہر"),
    ("orthopedic-surgeon", "Orthopedic Surgeon", "ہڈیوں کے ماہر"),
    ("ent-specialist", "ENT Specialist", "کان ناک گلا کے ماہر"),
    ("psychiatrist", "Psychiatrist", "نفسیاتی امراض کے ماہر"),
    ("neurologist", "Neurologist", "اعصابی امراض کے ماہر"),
    ("gastroenterologist", "Gastroenterologist", "معدے کے امراض کے ماہر"),
    ("pulmonologist", "Pulmonologist", "پھیپھڑوں کے امراض کے ماہر"),
    ("urologist", "Urologist", "مثانہ و پیشاب کے امراض کے ماہر"),
    ("ophthalmologist", "Ophthalmologist", "آنکھوں کے ماہر"),
    ("endocrinologist", "Endocrinologist", "غدود کے امراض کے ماہر"),
]


def seed() -> None:
    with Session(engine) as session:
        existing_slugs = set(session.exec(select(SpecializationTaxonomy.slug)).all())
        created = 0
        for slug, name_en, name_ur in SPECIALIZATIONS:
            if slug in existing_slugs:
                continue
            session.add(SpecializationTaxonomy(slug=slug, name_en=name_en, name_ur=name_ur))
            created += 1
        session.commit()
        print(f"seeded {created} new specializations ({len(existing_slugs)} already present)")


if __name__ == "__main__":
    seed()
