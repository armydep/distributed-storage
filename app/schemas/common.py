from __future__ import annotations

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="1-indexed page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page (max 100)")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginationMetadata(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int

    @classmethod
    def build(cls, *, page: int, page_size: int, total_items: int) -> PaginationMetadata:
        total_pages = (total_items + page_size - 1) // page_size if page_size else 0
        return cls(page=page, page_size=page_size, total_items=total_items, total_pages=total_pages)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: object | None = None
    correlation_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
