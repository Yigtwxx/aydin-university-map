"""``amap rag``: build the assistant's knowledge base."""

import json
from typing import Annotated

import typer

from amap_pipeline import paths

app = typer.Typer(help="Assistant knowledge-base commands.", no_args_is_help=True)


@app.command("vision")
def rag_vision(
    max_calls: Annotated[
        int | None, typer.Option(help="Stop after this many new scenes.")
    ] = None,
    rpm: Annotated[float, typer.Option(help="Requests per minute.")] = 10.0,
) -> None:
    """Describe every Florya panorama with Gemini (resumable JSONL)."""
    from amap_pipeline.env import require_env
    from amap_pipeline.rag.vision import describe_all, jobs_from_scenes

    scenes = json.loads((paths.derived_dir() / "scenes.json").read_text("utf-8"))
    written = describe_all(
        jobs_from_scenes(scenes),
        paths.tiles_dir(),
        paths.data_dir() / "rag" / "vision.jsonl",
        require_env("GEMINI_API_KEY"),
        rpm=rpm,
        max_calls=max_calls,
        progress=typer.echo,
    )
    typer.echo(f"vision: wrote {written} descriptions")


@app.command("build")
def rag_build(
    load: Annotated[bool, typer.Option(help="Also write chunks to Supabase.")] = True,
) -> None:
    """Build documents (spots, areas, campus), embed them and load the chunks."""
    from amap_pipeline.env import require_env
    from amap_pipeline.rag.corpus import (
        area_documents,
        campus_documents,
        spot_documents,
    )
    from amap_pipeline.rag.embed import document_text, embed_documents
    from amap_pipeline.rag.load import split_long

    scenes = json.loads((paths.derived_dir() / "scenes.json").read_text("utf-8"))
    rag_dir = paths.data_dir() / "rag"
    vision: dict[str, dict[str, object]] = {}
    vision_file = rag_dir / "vision.jsonl"
    if vision_file.is_file():
        for line in vision_file.read_text("utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                vision[record["scene"]] = record
    graph = json.loads((paths.data_dir() / "out" / "graph.geojson").read_text("utf-8"))
    nodes = {
        f["properties"]["id"]
        for f in graph["features"]
        if f["properties"]["feature"] == "node"
    }
    labels = {s["name"]: s["label"]["tr"] for s in scenes}
    docs = [
        piece
        for doc in (
            spot_documents(scenes, vision, nodes)
            + area_documents(scenes)
            + campus_documents(scenes, [labels[n] for n in nodes if n in labels])
        )
        for piece in split_long(doc)
    ]
    typer.echo(
        f"documents: {len(docs)} ({len(vision)} panoramas have vision descriptions)"
    )
    vectors = embed_documents(
        [(d.content_hash, document_text(d.title, d.content)) for d in docs],
        rag_dir / "embeddings.jsonl",
        require_env("GEMINI_API_KEY"),
        progress=typer.echo,
    )
    if not load:
        return
    import psycopg

    from amap_pipeline.rag.load import load_chunks

    with psycopg.connect(require_env("DATABASE_POOLER_URL"), autocommit=True) as conn:
        count = load_chunks(conn, docs, vectors)
    typer.echo(f"loaded {count} chunks into amap.chunks")
