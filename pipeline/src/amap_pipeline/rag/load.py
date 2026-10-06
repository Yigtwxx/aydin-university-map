"""Write documents and their embeddings to ``amap.chunks``.

A load replaces the chunks of the sources it covers in one transaction, so
removed or edited documents never linger next to their new versions.
"""

import json
from collections.abc import Mapping, Sequence

import psycopg

from amap_pipeline.rag.corpus import Document

MAX_CHUNK_CHARS = 1800


def split_long(doc: Document) -> list[Document]:
    """Split documents above ~400 tokens at sentence ends (most are short)."""
    if len(doc.content) <= MAX_CHUNK_CHARS:
        return [doc]
    pieces: list[str] = []
    current = ""
    for sentence in doc.content.split(". "):
        candidate = f"{current}. {sentence}" if current else sentence
        if len(candidate) > MAX_CHUNK_CHARS and current:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return [
        Document(
            doc.source,
            f"{doc.source_ref}#{i}",
            doc.lang,
            doc.title,
            piece,
            doc.metadata,
        )
        for i, piece in enumerate(pieces)
    ]


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"


def load_chunks(
    conn: psycopg.Connection,
    docs: Sequence[Document],
    vectors: Mapping[str, Sequence[float]],
) -> int:
    sources = sorted({d.source for d in docs})
    with conn.transaction():
        conn.execute("delete from amap.chunks where source = any(%s)", (sources,))
        with conn.cursor() as cur:
            cur.executemany(
                "insert into amap.chunks (content_hash, source, source_ref, lang, "
                "title, content, metadata, embedding) values "
                "(%s, %s, %s, %s, %s, %s, %s, %s::extensions.vector) "
                "on conflict (content_hash) do nothing",
                [
                    (
                        d.content_hash,
                        d.source,
                        d.source_ref,
                        d.lang,
                        d.title,
                        d.content,
                        json.dumps(d.metadata, ensure_ascii=False),
                        vector_literal(vectors[d.content_hash]),
                    )
                    for d in docs
                ],
            )
    return len(docs)
