from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import CurrentUser, require_role
from app.api.dependencies.database import DbSession
from app.api.dependencies.pagination import pagination_params, user_filter_params
from app.core.exceptions import InvalidStateError
from app.models.user import User, UserRole
from app.repositories.user import UserListFilters
from app.schemas.common import PaginationParams
from app.schemas.user import (
    PasswordChangeRequest,
    UserAdminUpdate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
from app.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse, summary="Get the current authenticated user")
async def get_me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse, summary="Update the current user's profile")
async def update_me(
    data: UserUpdate,
    current_user: CurrentUser,
    session: DbSession,
) -> UserResponse:
    user = await UserService(session).update_profile(current_user, data)
    return UserResponse.model_validate(user)


@router.post(
    "/me/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Change the current user's password",
)
async def change_my_password(
    data: PasswordChangeRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> None:
    await UserService(session).change_password(current_user, data)


@router.get(
    "",
    response_model=UserListResponse,
    summary="List users",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def list_users(
    session: DbSession,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[UserListFilters, Depends(user_filter_params)],
) -> UserListResponse:
    items, metadata = await UserService(session).list_users(
        filters=filters, page=pagination.page, page_size=pagination.page_size
    )
    return UserListResponse(
        items=[UserResponse.model_validate(item) for item in items], pagination=metadata
    )


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get a user by ID",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def get_user(user_id: uuid.UUID, session: DbSession) -> UserResponse:
    user = await UserService(session).get_by_id_or_raise(user_id)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update a user (administrative)",
)
async def update_user(
    user_id: uuid.UUID,
    data: UserAdminUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> UserResponse:
    service = UserService(session)
    user = await service.get_by_id_or_raise(user_id)
    if user.id == current_user.id and data.is_active is False:
        raise InvalidStateError("You cannot deactivate your own account")
    if user.id == current_user.id and data.role is not None and data.role != UserRole.ADMIN:
        raise InvalidStateError("You cannot change your own role")
    updated = await service.admin_update(user, data)
    return UserResponse.model_validate(updated)


@router.post(
    "/{user_id}/activate",
    response_model=UserResponse,
    summary="Activate a user",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def activate_user(user_id: uuid.UUID, session: DbSession) -> UserResponse:
    service = UserService(session)
    user = await service.get_by_id_or_raise(user_id)
    user = await service.set_active(user, True)
    return UserResponse.model_validate(user)


@router.post(
    "/{user_id}/deactivate",
    response_model=UserResponse,
    summary="Deactivate a user",
)
async def deactivate_user(
    user_id: uuid.UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> UserResponse:
    if user_id == current_user.id:
        raise InvalidStateError("You cannot deactivate your own account")
    service = UserService(session)
    user = await service.get_by_id_or_raise(user_id)
    user = await service.set_active(user, False)
    return UserResponse.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a user",
)
async def delete_user(
    user_id: uuid.UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> None:
    if user_id == current_user.id:
        raise InvalidStateError("You cannot delete your own account")
    service = UserService(session)
    user = await service.get_by_id_or_raise(user_id)
    await service.delete_user(user)
