#!/usr/bin/env sh
set -eu

echo "Waiting for PostgreSQL at ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
python -c "
import asyncio
import os
import sys

import asyncpg


async def wait_for_db() -> None:
    for attempt in range(60):
        try:
            connection = await asyncpg.connect(
                host=os.environ.get('POSTGRES_HOST', 'db'),
                port=int(os.environ.get('POSTGRES_PORT', '5432')),
                user=os.environ.get('POSTGRES_USER', 'postgres'),
                password=os.environ.get('POSTGRES_PASSWORD', 'postgres'),
                database=os.environ.get('POSTGRES_DB', 'app'),
                timeout=3,
            )
            await connection.close()
            return
        except Exception:
            await asyncio.sleep(1)
    print('Database did not become ready in time', file=sys.stderr)
    sys.exit(1)


asyncio.run(wait_for_db())
"

echo "Applying database migrations..."
alembic upgrade head

echo "Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
