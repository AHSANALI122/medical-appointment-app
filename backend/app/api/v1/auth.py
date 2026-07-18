from fastapi import APIRouter, Depends, Request, Response
from sqlmodel import Session

from app.api.deps import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    REFRESH_COOKIE_NAME,
    get_current_user,
)
from app.core.cookies import clear_auth_cookies, issue_csrf_cookie, set_auth_cookies
from app.core.db import get_session
from app.core.exceptions import UnauthorizedError
from app.core.rate_limit import AUTH_RATE_LIMIT, rate_limit
from app.schemas.auth import (
    DoctorRegisterResponse,
    LoginRequest,
    RegisterDoctorRequest,
    RegisterPatientRequest,
    UpdateNotificationPreferenceRequest,
    UserPublic,
)
from app.services import auth_service

router = APIRouter()

_tier, _limit, _window = AUTH_RATE_LIMIT
_auth_rate_limit = Depends(rate_limit(_tier, limit=_limit, window_seconds=_window))


@router.post("/register/patient", response_model=UserPublic, status_code=201, dependencies=[_auth_rate_limit])
def register_patient(
    body: RegisterPatientRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> UserPublic:
    user = auth_service.register_patient(
        session,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        phone=body.phone,
    )
    _, access_token, refresh_token = auth_service.login(session, email=body.email, password=body.password)
    response.headers[CSRF_HEADER_NAME] = set_auth_cookies(
        response, access_token=access_token, refresh_token=refresh_token
    )
    return UserPublic.model_validate(user, from_attributes=True)


@router.post(
    "/register/doctor", response_model=DoctorRegisterResponse, status_code=201, dependencies=[_auth_rate_limit]
)
def register_doctor(
    body: RegisterDoctorRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> DoctorRegisterResponse:
    user, doctor_profile = auth_service.register_doctor(
        session,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        phone=body.phone,
        pmc_number=body.pmc_number,
        specialization_id=body.specialization_id,
        consultation_fee=body.consultation_fee,
    )
    _, access_token, refresh_token = auth_service.login(session, email=body.email, password=body.password)
    response.headers[CSRF_HEADER_NAME] = set_auth_cookies(
        response, access_token=access_token, refresh_token=refresh_token
    )
    return DoctorRegisterResponse(
        user=UserPublic.model_validate(user, from_attributes=True),
        verification_status=doctor_profile.verification_status,
    )


@router.post("/login", response_model=UserPublic, dependencies=[_auth_rate_limit])
def login(
    body: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> UserPublic:
    user, access_token, refresh_token = auth_service.login(session, email=body.email, password=body.password)
    response.headers[CSRF_HEADER_NAME] = set_auth_cookies(
        response, access_token=access_token, refresh_token=refresh_token
    )
    return UserPublic.model_validate(user, from_attributes=True)


@router.post("/refresh", response_model=UserPublic)
def refresh(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> UserPublic:
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise UnauthorizedError("no refresh token")

    user, access_token, new_refresh_token = auth_service.refresh_session(session, refresh_token=refresh_token)
    response.headers[CSRF_HEADER_NAME] = set_auth_cookies(
        response, access_token=access_token, refresh_token=new_refresh_token
    )
    return UserPublic.model_validate(user, from_attributes=True)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> None:
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token:
        auth_service.revoke_refresh_token(session, refresh_token=refresh_token)
    clear_auth_cookies(response)


@router.get("/csrf")
def csrf(request: Request, response: Response) -> dict[str, str]:
    """Hand the double-submit CSRF token to the (cross-site) frontend.

    On a fresh page load the Vercel frontend has no token in memory and can't
    read the backend-domain cookie via document.cookie, so it calls this to
    re-learn the value before making any mutating request. Returns the token in
    the body and the X-CSRF-Token header; issues a cookie if none exists yet.
    """
    token = issue_csrf_cookie(request.cookies.get(CSRF_COOKIE_NAME), response)
    response.headers[CSRF_HEADER_NAME] = token
    return {"csrf_token": token}


@router.get("/me", response_model=UserPublic)
def me(user=Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(user, from_attributes=True)


@router.put("/me/notification-preference", response_model=UserPublic)
def update_notification_preference(
    body: UpdateNotificationPreferenceRequest,
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
) -> UserPublic:
    """F25 — the only escape hatch a patient/doctor has to switch to
    SMS-first delivery ahead of any bounce; identity from JWT as always."""
    user.notification_preference = body.notification_preference
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserPublic.model_validate(user, from_attributes=True)
