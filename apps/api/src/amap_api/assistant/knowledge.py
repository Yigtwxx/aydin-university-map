"""Semantic search over ``amap.chunks`` (Gemini query embedding + pgvector)."""

from typing import Any

from psycopg.rows import dict_row

from amap_api.db import Database

EMBEDDING_MODEL = "gemini-embedding-2"
DIMENSIONS = 768


def query_text(question: str) -> str:
    # Same task prefix as the pipeline (amap_pipeline.rag.embed.query_text).
    return f"task: search result | query: {question}"


class Knowledge:
    def __init__(self, database: Database, gemini_api_key: str) -> None:
        from google import genai

        self.database = database
        self.client = genai.Client(api_key=gemini_api_key)

    async def embed_query(self, question: str) -> list[float]:
        from google.genai import types

        result = await self.client.aio.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=query_text(question),
            config=types.EmbedContentConfig(output_dimensionality=DIMENSIONS),
        )
        embeddings = result.embeddings or []
        return list(embeddings[0].values or []) if embeddings else []

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
                (literal, lang, literal, k),
            )
            return await cur.fetchall()
