from app.core.security import hash_password
from app.models.doctor import ClinicLocation, DoctorProfile
from app.models.enums import DoctorVerificationStatus, UserRole
from app.models.user import User


def _make_doctor(session, specialization, *, email, full_name, fee, city, verified=True):
    user = User(
        email=email,
        password_hash=hash_password("password123"),
        role=UserRole.DOCTOR,
        full_name=full_name,
    )
    session.add(user)
    session.flush()
    doctor = DoctorProfile(
        user_id=user.id,
        specialization_id=specialization.id,
        pmc_number=f"PMC-{email}",
        consultation_fee=fee,
        verification_status=(
            DoctorVerificationStatus.VERIFIED if verified else DoctorVerificationStatus.UNVERIFIED
        ),
    )
    session.add(doctor)
    session.commit()
    session.refresh(doctor)
    session.add(ClinicLocation(doctor_id=doctor.id, name="Clinic", address="1 Road", city=city))
    session.commit()
    return doctor


class TestDoctorSearch:
    def test_only_verified_doctors_appear(self, client, session, specialization):
        _make_doctor(
            session, specialization, email="v1@example.com", full_name="Dr. Verified One",
            fee=1000, city="Lahore", verified=True,
        )
        _make_doctor(
            session, specialization, email="u1@example.com", full_name="Dr. Unverified One",
            fee=1000, city="Lahore", verified=False,
        )

        resp = client.get("/api/v1/doctors")
        assert resp.status_code == 200
        names = [d["full_name"] for d in resp.json()["items"]]
        assert "Dr. Verified One" in names
        assert "Dr. Unverified One" not in names

    def test_filter_by_city(self, client, session, specialization):
        _make_doctor(
            session, specialization, email="lhr@example.com", full_name="Dr. Lahori",
            fee=1000, city="Lahore",
        )
        _make_doctor(
            session, specialization, email="khi@example.com", full_name="Dr. Karachiwala",
            fee=1000, city="Karachi",
        )

        resp = client.get("/api/v1/doctors", params={"city": "Karachi"})
        assert resp.status_code == 200
        names = [d["full_name"] for d in resp.json()["items"]]
        assert names == ["Dr. Karachiwala"]

    def test_filter_by_fee_range(self, client, session, specialization):
        _make_doctor(
            session, specialization, email="cheap@example.com", full_name="Dr. Cheap",
            fee=500, city="Lahore",
        )
        _make_doctor(
            session, specialization, email="pricey@example.com", full_name="Dr. Pricey",
            fee=5000, city="Lahore",
        )

        resp = client.get("/api/v1/doctors", params={"fee_min": 1000, "fee_max": 6000})
        assert resp.status_code == 200
        names = [d["full_name"] for d in resp.json()["items"]]
        assert names == ["Dr. Pricey"]

    def test_name_search_is_case_insensitive_substring(self, client, session, specialization):
        _make_doctor(
            session, specialization, email="ahmed@example.com", full_name="Dr. Bilal Ahmed",
            fee=1000, city="Lahore",
        )
        _make_doctor(
            session, specialization, email="khan@example.com", full_name="Dr. Sana Khan",
            fee=1000, city="Lahore",
        )

        resp = client.get("/api/v1/doctors", params={"name": "ahmed"})
        assert resp.status_code == 200
        names = [d["full_name"] for d in resp.json()["items"]]
        assert names == ["Dr. Bilal Ahmed"]

    def test_sort_by_fee(self, client, session, specialization):
        _make_doctor(
            session, specialization, email="mid@example.com", full_name="Dr. Mid",
            fee=2000, city="Lahore",
        )
        _make_doctor(
            session, specialization, email="low@example.com", full_name="Dr. Low",
            fee=500, city="Lahore",
        )
        _make_doctor(
            session, specialization, email="high@example.com", full_name="Dr. High",
            fee=8000, city="Lahore",
        )

        resp = client.get("/api/v1/doctors", params={"sort": "fee_asc"})
        fees = [d["consultation_fee"] for d in resp.json()["items"]]
        assert fees == sorted(fees)

        resp_desc = client.get("/api/v1/doctors", params={"sort": "fee_desc"})
        fees_desc = [d["consultation_fee"] for d in resp_desc.json()["items"]]
        assert fees_desc == sorted(fees_desc, reverse=True)

    def test_doctor_with_multiple_clinics_in_same_city_appears_once(
        self, client, session, specialization
    ):
        doctor = _make_doctor(
            session, specialization, email="multi@example.com", full_name="Dr. Multi",
            fee=1000, city="Lahore",
        )
        session.add(
            ClinicLocation(doctor_id=doctor.id, name="Second Clinic", address="2 Road", city="Lahore")
        )
        session.commit()

        resp = client.get("/api/v1/doctors", params={"city": "Lahore"})
        names = [d["full_name"] for d in resp.json()["items"]]
        assert names.count("Dr. Multi") == 1

    def test_pagination(self, client, session, specialization):
        for i in range(5):
            _make_doctor(
                session, specialization, email=f"page{i}@example.com", full_name=f"Dr. Page {i}",
                fee=1000, city="Lahore",
            )

        resp = client.get("/api/v1/doctors", params={"page": 1, "page_size": 2})
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5

    def test_search_result_includes_next_available_slot_field(
        self, client, session, specialization, verified_doctor, clinic_location, availability_rule
    ):
        resp = client.get("/api/v1/doctors")
        assert resp.status_code == 200
        item = next(d for d in resp.json()["items"] if d["id"] == str(verified_doctor.id))
        assert "next_available_slot_utc" in item
        assert item["next_available_slot_utc"] is not None
