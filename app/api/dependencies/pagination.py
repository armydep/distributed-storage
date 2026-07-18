from __future__ import annotations

from typing import Annotated

from fastapi import Query

from app.models.user import UserRole
from app.repositories.user import UserListFilters
from app.schemas.common import PaginationParams


def pagination_params(
    page: Annotated[int, Query(ge=1, description="1-indexed page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page (max 100)")] = 20,
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


def user_filter_params(
    role: Annotated[UserRole | None, Query(description="Filter by role")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by active status")] = None,
    search: Annotated[
        str | None, Query(max_length=255, description="Search by username or email")
    ] = None,
) -> UserListFilters:
    return UserListFilters(role=role, is_active=is_active, search=search)
