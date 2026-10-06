"""Optional Postgres access (Supabase through the transaction pooler).

The API works without a database: routing and place search run on the
in-memory graph. With ``AMAP_API_DATABASE_URL`` set it adds building data,
typo-tolerant place search, the assistant's knowledge base and its answer
cache. The URL uses the least-privilege ``amap_api`` role (``amap db api-role``).
"""

import logging
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("amap_api.db")

# Below this trigram similarity a place is not offered as a typo correction.
MIN_SIMILARITY = 0.3


class Database:
    def __init__(self, url: str) -> None:
        # Transaction pooling (pgbouncer-style) cannot keep prepared statements.
        self.pool = AsyncConnectionPool(
            url,
            min_size=0,
            max_size=4,
            open=False,
            timeout=5.0,
            kwargs={"prepare_threshold": None, "autocommit": True},
        )

    async def open(self) -> None:
        await self.pool.open(wait=False)

    async def close(self) -> None:
        await self.pool.close()

    async def ping(self) -> bool:
        """``select 1``; the keepalive hits this so Supabase never pauses."""
        try:
            async with self.pool.connection(timeout=3.0) as conn:
                await conn.execute("select 1")
            return True
        except Exception as exc:
            log.warning("database ping failed: %s", type(exc).__name__)
            return False

    async def buildings(self, campus_only: bool) -> list[dict[str, Any]]:
        async with (
            self.pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "select id, code, name, campus, height_m, height_source, "
                "extensions.st_x(extensions.st_centroid(footprint)) as lng, "
                "extensions.st_y(extensions.st_centroid(footprint)) as lat "
                "from amap.buildings where campus or not %s "
                "order by code nulls last, id",
                (campus_only,),
            )
            return await cur.fetchall()

    async def similar_place_ids(self, key: str, limit: int) -> list[str]:
        """Place ids whose search key is closest to ``key`` (pg_trgm)."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select id from amap.places "
                "where extensions.similarity(search_key, %s) >= %s "
                "order by extensions.similarity(search_key, %s) desc limit %s",
                (key, MIN_SIMILARITY, key, limit),
            )
            return [row[0] for row in await cur.fetchall()]
