"""SQLAlchemy models.

Importing this package registers all models on ``Base.metadata``, which is
required for Alembic autogeneration to see every table.
"""

from app.models.base import Base
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole

__all__ = ["Base", "RefreshToken", "User", "UserRole"]
