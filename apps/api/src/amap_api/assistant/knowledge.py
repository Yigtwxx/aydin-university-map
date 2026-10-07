"""Semantic search over ``amap.chunks`` (Gemini query embedding + pgvector).

Query vectors are cached (LRU): the free tier allows 1,000 embedding
requests a day, and visitors ask the same questions again and again.

Results are diversified: many places have several 360° spots with the same
title and area ("T Blok Bahçe" four times), and without a cap they fill the
top five and push out the block's own document (eval Step 4.4, tr-know-01).
"""

from array import array
from collections import Counter, OrderedDict
from collections.abc import Sequence
from typing import Any

from psycopg.rows import dict_row

from amap_api.db import Database

EMBEDDING_MODEL = "gemini-embedding-2"
DIMENSIONS = 768
QUERY_CACHE_SIZE = 512  # float32 arrays: about 1.5 MB when full
# At most this many hits per (title, area). One was too few in the eval: the
# two "D Blok Giriş" spots describe different sides of the entrance.
MAX_PER_PLACE = 2
CANDIDATES = 4  # fetch k * CANDIDATES rows, then diversify


def diversify(rows: Sequence[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """The best ``k`` rows (in order), at most MAX_PER_PLACE per title and area."""
    kept: list[dict[str, Any]] = []
    seen: Counter[tuple[str, str | None]] = Counter()
    for row in rows:
        key = (row["title"], (row.get("metadata") or {}).get("area_tr"))
        if seen[key] < MAX_PER_PLACE:
            seen[key] += 1
            kept.append(row)
            if len(kept) == k:
                break
    return kept


def query_text(question: str) -> str:
    # Same task prefix as the pipeline (amap_pipeline.rag.embed.query_text).
    return f"task: search result | query: {question}"


class Knowledge:
    def __init__(self, database: Database, gemini_api_key: str) -> None:
        from google import genai

        self.database = database
        self.client = genai.Client(api_key=gemini_api_key)
        self._vectors: OrderedDict[str, array[float]] = OrderedDict()

    async def embed_query(self, question: str) -> list[float]:
        from google.genai import types

        text = " ".join(question.split())
        key = text.casefold()
        cached = self._vectors.get(key)
        if cached is not None:
            self._vectors.move_to_end(key)
            return cached.tolist()
        result = await self.client.aio.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=query_text(text),
            config=types.EmbedContentConfig(output_dimensionality=DIMENSIONS),
        )
        embeddings = result.embeddings or []
        vector = list(embeddings[0].values or []) if embeddings else []
        if vector:
            self._vectors[key] = array("f", vector)
            if len(self._vectors) > QUERY_CACHE_SIZE:
                self._vectors.popitem(last=False)
        return vector

    async def search(
        self, question: str, lang: str, k: int = 5
    ) -> list[dict[str, Any]]:
        vector = await self.embed_query(question)
        if not vector:
            return []
        literal = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
        async with (
            self.database.pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "select title, content, source, source_ref, metadata, "
                "1 - (embedding operator(extensions.<=>) %s::extensions.vector) "
                "as score from amap.chunks where lang = %s "
                "order by embedding operator(extensions.<=>) %s::extensions.vector "
                "limit %s",
                (literal, lang, literal, k * CANDIDATES),
            )
            return diversify(await cur.fetchall(), k)
