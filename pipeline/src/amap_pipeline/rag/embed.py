"""Gemini embeddings (768 dims) with a content-hash cache.

``gemini-embedding-2`` has no task type parameter; documents and queries get
the task prefixes from Google's embedding guide instead, so a query embeds
closer to the documents that answer it. The API uses the same query prefix.
"""

import json
from collections.abc import Callable, Sequence
from pathlib import Path

EMBEDDING_MODEL = "gemini-embedding-2"
DIMENSIONS = 768
BATCH = 50


def document_text(title: str, content: str) -> str:
    return f"title: {title} | text: {content}"


def query_text(question: str) -> str:
    return f"task: search result | query: {question}"


def load_cache(path: Path) -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    if path.is_file():
        for line in path.read_text("utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                cache[record["hash"]] = record["vector"]
    return cache


def embed_documents(
    items: Sequence[tuple[str, str]],
    cache_path: Path,
    api_key: str,
    progress: Callable[[str], None] = print,
) -> dict[str, list[float]]:
    """``items``: (content hash, text). Returns hash -> vector for every item."""
    from google import genai
    from google.genai import errors, types
    from tenacity import (
        retry,
        retry_if_exception,
        stop_after_attempt,
        wait_exponential,
    )

    cache = load_cache(cache_path)
    todo = [(h, t) for h, t in items if h not in cache]
    progress(f"embed: {len(todo)} new of {len(items)} ({len(cache)} cached)")
    if not todo:
        return {h: cache[h] for h, _ in items}

    client = genai.Client(api_key=api_key)
    config = types.EmbedContentConfig(output_dimensionality=DIMENSIONS)

    def retryable(exc: BaseException) -> bool:
        return isinstance(exc, errors.APIError) and exc.code in (429, 500, 503)

    @retry(
        retry=retry_if_exception(retryable),
        wait=wait_exponential(multiplier=8, min=8, max=120),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    def call(texts: list[str]) -> list[list[float]]:
        # One Content per text: the multimodal model embeds a plain list of
        # strings as the parts of a single input and returns one vector.
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=[types.Content(parts=[types.Part(text=t)]) for t in texts],
            config=config,
        )
        return [list(e.values or []) for e in result.embeddings or []]

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("a", encoding="utf-8") as out:
        for start in range(0, len(todo), BATCH):
            batch = todo[start : start + BATCH]
            vectors = call([t for _, t in batch])
            if len(vectors) != len(batch):
                raise RuntimeError("embedding count does not match the batch")
            for (h, _), vector in zip(batch, vectors, strict=True):
                cache[h] = vector
                out.write(json.dumps({"hash": h, "vector": vector}) + "\n")
            out.flush()
            progress(f"embed: {min(start + BATCH, len(todo))}/{len(todo)}")
    return {h: cache[h] for h, _ in items}
