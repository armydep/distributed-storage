"""Aggregates all versioned API routes under a single router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import auth, users

api_v1_router = APIRouter()
api_v1_router.include_router(auth.router)
api_v1_router.include_router(users.router)
