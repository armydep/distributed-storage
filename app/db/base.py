"""Single import point exposing metadata for Alembic autogeneration.

``alembic/env.py`` imports ``Base`` from here (which transitively imports
``app.models``, registering every table) so ``Base.metadata`` always
reflects the full current schema.
"""

from app.models import Base

__all__ = ["Base"]
