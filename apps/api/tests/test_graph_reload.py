"""A running API picks up a newly published graph (no restart needed)."""

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from amap_api.main import create_app
from amap_api.settings import Settings
from amap_contracts.graph import Graph


def _write(path: Path, graph: Graph, mtime: float) -> None:
    path.write_text(json.dumps(graph.to_geojson()), encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_graph_reload_new_file_replaces_routes(graph: Graph, tmp_path: Path) -> None:
    source = tmp_path / "graph.geojson"
    _write(source, graph, 1_000_000)
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]  # never read the local .env
        graph_source=str(source),
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        first = client.post("/route", json={"source": "a", "target": "c"})
        assert first.json()["node_ids"] == ["a", "b", "c"], first.json()

        # The new graph drops b: the only way to c is now through d.
        edges = [e for e in graph.edges if "b" not in (e.source, e.target)]
        nodes = [n for n in graph.nodes if n.id != "b"]
        _write(
            source,
            graph.model_copy(update={"nodes": nodes, "edges": edges}),
            2_000_000,
        )
        app.state.graph_watch.checked_at = float("-inf")
        second = client.post("/route", json={"source": "a", "target": "c"})
        assert second.json()["node_ids"] == ["a", "d", "c"], second.json()
        assert "b" not in {p["id"] for p in client.get("/places?limit=50").json()}


def test_graph_reload_unchanged_file_keeps_the_store(
    graph: Graph, tmp_path: Path
) -> None:
    source = tmp_path / "graph.geojson"
    _write(source, graph, 1_000_000)
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]  # never read the local .env
        graph_source=str(source),
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        store = app.state.store
        app.state.graph_watch.checked_at = float("-inf")
        client.get("/graph")
        assert app.state.store is store, "reloaded an unchanged graph"
