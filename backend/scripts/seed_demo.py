"""F29 — one command bootstraps a demo environment.

    uv run python scripts/seed_demo.py

Seeds the taxonomy (delegating to seed_taxonomy.py rather than duplicating
the list), 20 verified doctors across specializations and cities, each with
a clinic and a weekly availability schedule, plus 3 demo patients — one of
them with a dependent profile so family accounts (F20) are demoable.

Idempotent: re-running creates nothing new. Keyed off deterministic emails
(`doctor1@demo.medbook.pk`, …) rather than random ones, so this is safe to
run repeatedly against a staging DB.

REFUSES TO RUN when ENVIRONMENT=production — these are accounts with a
published password.
"""

import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.doctor import AvailabilityRule, ClinicLocation, DoctorProfile  # noqa: E402
from app.models.enums import DoctorVerificationStatus, UserRole, Weekday  # noqa: E402
from app.models.taxonomy import SpecializationTaxonomy  # noqa: E402
from app.models.user import PatientProfile, User  # noqa: E402
from scripts.seed_taxonomy import seed as seed_taxonomy  # noqa: E402

DEMO_PASSWORD = "demo1234"  # noqa: S105 — demo data, guarded against production below

# (name, specialization slug, fee PKR, city, clinic name, address)
DOCTORS = [
    ("Dr. Ayesha Khan", "general-physician", 1500, "Lahore", "Gulberg Family Clinic", "12-A Main Blvd, Gulberg III, Lahore"),
    ("Dr. Bilal Ahmed", "cardiologist", 4000, "Lahore", "Heart Care Centre", "45 Jail Road, Lahore"),
    ("Dr. Fatima Malik", "dermatologist", 2500, "Karachi", "SkinFirst Clinic", "88 Khayaban-e-Shahbaz, DHA, Karachi"),
    ("Dr. Usman Tariq", "dentist", 2000, "Islamabad", "Bright Smile Dental", "Plot 7, F-8 Markaz, Islamabad"),
    ("Dr. Sana Iqbal", "gynecologist", 3000, "Lahore", "Noor Women's Clinic", "23 Model Town Link Rd, Lahore"),
    ("Dr. Hamza Sheikh", "pediatrician", 2000, "Karachi", "Little Steps Children's Clinic", "5 Clifton Block 4, Karachi"),
    ("Dr. Zainab Raza", "orthopedic-surgeon", 3500, "Rawalpindi", "Bone & Joint Centre", "31 Murree Road, Rawalpindi"),
    ("Dr. Ali Hassan", "ent-specialist", 2200, "Faisalabad", "ENT Care Faisalabad", "17 Kohinoor City, Faisalabad"),
    ("Dr. Maryam Butt", "psychiatrist", 3500, "Lahore", "Mind Wellness Clinic", "9 Cavalry Ground, Lahore"),
    ("Dr. Omar Farooq", "neurologist", 4500, "Karachi", "NeuroCare Karachi", "62 Shahrah-e-Faisal, Karachi"),
    ("Dr. Hina Javed", "gastroenterologist", 3200, "Islamabad", "Digestive Health Centre", "14 Blue Area, Islamabad"),
    ("Dr. Kamran Shah", "pulmonologist", 3000, "Peshawar", "Chest & Lung Clinic", "3 University Road, Peshawar"),
    ("Dr. Nadia Aslam", "urologist", 3300, "Lahore", "Urology Specialists", "77 Johar Town, Lahore"),
    ("Dr. Imran Qureshi", "ophthalmologist", 2800, "Multan", "Clear Vision Eye Clinic", "21 Bosan Road, Multan"),
    ("Dr. Rabia Nasir", "endocrinologist", 3800, "Karachi", "Diabetes & Hormone Centre", "40 Gulshan-e-Iqbal, Karachi"),
    ("Dr. Ahmed Zubair", "general-physician", 1200, "Quetta", "City Medical Centre", "8 Jinnah Road, Quetta"),
    ("Dr. Sadia Rehman", "dermatologist", 2400, "Islamabad", "Glow Skin Clinic", "26 F-10 Markaz, Islamabad"),
    ("Dr. Tariq Mehmood", "cardiologist", 4200, "Rawalpindi", "Pulse Heart Institute", "52 Saddar, Rawalpindi"),
    ("Dr. Komal Yousaf", "pediatrician", 1800, "Sialkot", "Kids Health Clinic", "11 Paris Road, Sialkot"),
    ("Dr. Faisal Abbas", "dentist", 1900, "Lahore", "Dental Studio Lahore", "3 DHA Phase 5, Lahore"),
]

# (full_name, email, dependents)
PATIENTS = [
    ("Asad Mehmood", "asad@demo.medbook.pk", []),
    ("Hira Siddiqui", "hira@demo.medbook.pk", [("Yusuf Siddiqui", "son")]),
    ("Bilal Chaudhry", "bilal@demo.medbook.pk", []),
]

# The k6 load test (loadtest/booking_load_test.js) runs 50 booking VUs, and
# the state machine caps a profile at 3 active drafts (and 1 per doctor).
# Sharing the 3 demo patients above across 50 VUs would mean nearly every
# request bounced off that abuse guard — the run would look "fine" while
# measuring almost no booking throughput. One account per VU keeps the
# guard out of the way so the test exercises what it claims to.
LOAD_TEST_PATIENT_COUNT = 50

WEEKDAYS = (Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI)


def _guard_production() -> None:
    settings = get_settings()
    if settings.is_production:
        raise SystemExit(
            "refusing to seed demo data into production — these accounts share a "
            "known password. Set ENVIRONMENT to something other than 'production'."
        )


def _seed_doctors(session: Session) -> int:
    specializations = {
        s.slug: s.id for s in session.exec(select(SpecializationTaxonomy)).all()
    }
    created = 0

    for index, (name, slug, fee, city, clinic_name, address) in enumerate(DOCTORS, start=1):
        email = f"doctor{index}@demo.medbook.pk"
        if session.exec(select(User).where(User.email == email)).first() is not None:
            continue

        user = User(
            email=email,
            password_hash=hash_password(DEMO_PASSWORD),
            role=UserRole.DOCTOR,
            full_name=name,
            phone=f"+9230000000{index:02d}",
        )
        session.add(user)
        session.flush()

        doctor = DoctorProfile(
            user_id=user.id,
            specialization_id=specializations[slug],
            qualifications="MBBS, FCPS",
            bio=f"{name} is an experienced {slug.replace('-', ' ')} practising in {city}.",
            consultation_fee=fee,
            pmc_number=f"PMC-DEMO-{index:03d}",
            # Verified, because an unverified doctor is invisible to search
            # and the demo's whole point is a browsable directory.
            verification_status=DoctorVerificationStatus.VERIFIED,
        )
        session.add(doctor)
        session.flush()

        clinic = ClinicLocation(
            doctor_id=doctor.id, name=clinic_name, address=address, city=city
        )
        session.add(clinic)
        session.flush()

        for weekday in WEEKDAYS:
            session.add(
                AvailabilityRule(
                    doctor_id=doctor.id,
                    clinic_location_id=clinic.id,
                    weekday=weekday,
                    start_time_local=time(17, 0),
                    end_time_local=time(21, 0),
                    slot_duration_minutes=30,
                )
            )
        created += 1

    session.commit()
    return created


def _seed_patients(session: Session) -> int:
    roster = list(PATIENTS) + [
        (f"Load Test User {n}", f"load{n}@demo.medbook.pk", [])
        for n in range(1, LOAD_TEST_PATIENT_COUNT + 1)
    ]

    created = 0
    for full_name, email, dependents in roster:
        if session.exec(select(User).where(User.email == email)).first() is not None:
            continue

        user = User(
            email=email,
            password_hash=hash_password(DEMO_PASSWORD),
            role=UserRole.PATIENT,
            full_name=full_name,
        )
        session.add(user)
        session.flush()

        # Every patient needs a 'self' profile — bookings reference
        # patient_profile_id, never user_id, and deps.resolve_self_patient_profile
        # 404s without it.
        session.add(
            PatientProfile(user_id=user.id, relationship_label="self", full_name=full_name)
        )
        for dependent_name, label in dependents:
            session.add(
                PatientProfile(user_id=user.id, relationship_label=label, full_name=dependent_name)
            )
        created += 1

    session.commit()
    return created


def _seed_admin(session: Session) -> int:
    email = "admin@demo.medbook.pk"
    if session.exec(select(User).where(User.email == email)).first() is not None:
        return 0
    session.add(
        User(
            email=email,
            password_hash=hash_password(DEMO_PASSWORD),
            role=UserRole.ADMIN,
            full_name="Demo Admin",
        )
    )
    session.commit()
    return 1


def seed() -> None:
    _guard_production()
    seed_taxonomy()

    with Session(engine) as session:
        doctors = _seed_doctors(session)
        patients = _seed_patients(session)
        admins = _seed_admin(session)

    print(f"seeded {doctors} doctors, {patients} patients, {admins} admin")
    print(f"all demo accounts use password: {DEMO_PASSWORD}")
    print("  doctors:   doctor1@demo.medbook.pk … doctor20@demo.medbook.pk")
    print("  patients:  asad@ / hira@ / bilal@demo.medbook.pk")
    print(f"  load test: load1@ … load{LOAD_TEST_PATIENT_COUNT}@demo.medbook.pk")
    print("  admin:     admin@demo.medbook.pk")


if __name__ == "__main__":
    seed()
