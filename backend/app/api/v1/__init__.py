from fastapi import APIRouter

from app.api.v1 import auth, bookings, doctors

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(doctors.router, prefix="/doctors", tags=["doctors"])
api_router.include_router(bookings.router, prefix="/bookings", tags=["bookings"])
