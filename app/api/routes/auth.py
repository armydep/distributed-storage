from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.database import DbSession
from app.schemas.auth import RefreshTokenRequest, TokenResponse
from app.schemas.user import UserCreate, UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(data: UserCreate, session: DbSession) -> UserResponse:
    user = await AuthService(session).register(data)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse, summary="Log in and obtain a token pair")
async def login(
    session: DbSession,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    """OAuth2 password flow. ``username`` may be either the username or email."""
    service = AuthService(session)
    user = await service.authenticate(form_data.username, form_data.password)
    tokens = await service.issue_tokens(user)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/refresh", response_model=TokenResponse, summary="Exchange a refresh token for a new pair"
)
async def refresh(data: RefreshTokenRequest, session: DbSession) -> TokenResponse:
    tokens = await AuthService(session).refresh(data.refresh_token)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke a refresh token, ending the associated session",
)
async def logout(
    data: RefreshTokenRequest,
    session: DbSession,
    _current_user: CurrentUser,
) -> None:
    await AuthService(session).logout(data.refresh_token)
