"""Auth routes: login/logout (JWT) and registration."""

from fastapi import APIRouter

from app.domain.auth import UserCreate, UserRead
from app.infra.auth.auth import auth_backend, fastapi_users

router = APIRouter()

router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)

router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
