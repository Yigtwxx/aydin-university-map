"""Synthetic walking graph for API tests (no real campus data)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from amap_api.db import Database
from amap_api.graph_store import GraphStore
from amap_api.main import create_app
from amap_api.settings import Settings
from amap_contracts.graph import (
    WALKING_SPEED_MPS,
    Edge,
    EdgeKind,
    EdgeOrigin,
    Graph,
    GraphMeta,
    LengthSource,
    LocalizedText,
    Node,
    NodeKind,
    PoseSource,
)

# (x east, y north) metres; a -> b -> c is an L turning right; d is reachable
# from a via stairs (short) or via b-c (long); e is isolated.
LAYOUT: dict[str, tuple[float, float, NodeKind, str, str]] = {
    "a": (0.0, 0.0, NodeKind.OUTDOOR, "Kampüs", "Campus"),
    "b": (0.0, 20.0, NodeKind.OUTDOOR, "Kampüs", "Campus"),
    "c": (20.0, 20.0, NodeKind.ENTRANCE, "A Blok Girişi", "A Block Entrance"),
    "d": (20.0, 0.0, NodeKind.ENTRANCE, "Kütüphane Giriş", "Library Entrance"),
    "e": (200.0, 200.0, NodeKind.OUTDOOR, "Otopark", "Car Park"),
}
EDGES = [("a", "b", EdgeKind.OUTDOOR), ("b", "c", EdgeKind.OUTDOOR),
         ("c", "d", EdgeKind.OUTDOOR), ("a", "d", EdgeKind.STAIRS)]  # fmt: skip


def _node(node_id: str) -> Node:
    x, y, kind, tr, en = LAYOUT[node_id]
    return Node(
        id=node_id,
        kind=kind,
        lat=40.9915 + y / 111_320.0,
        lng=28.7971 + x / 84_000.0,
        alt_m=1.6,
        enu=(x, y, 1.6),
        heading_deg=0.0,
        pose_source=PoseSource.SFM,
        label=LocalizedText(tr=tr, en=en),
        area=LocalizedText(tr="Florya Kampüs", en="Florya Campus"),
        building="A" if node_id == "c" else None,
    )


def _edge(a: str, b: str, kind: EdgeKind) -> Edge:
    (xa, ya, *_), (xb, yb, *_) = LAYOUT[a], LAYOUT[b]
    length = ((xa - xb) ** 2 + (ya - yb) ** 2) ** 0.5
    return Edge(
        id=f"{a}|{b}",
        source=a,
        target=b,
        kind=kind,
        origin=EdgeOrigin.TOUR,
        length_m=length,
        cost_s=length / WALKING_SPEED_MPS,
        length_source=LengthSource.SFM,
    )


@pytest.fixture
def graph() -> Graph:
    meta = GraphMeta(
        generated_at=datetime(2026, 10, 6, tzinfo=UTC),
        run_id="test",
        origin_lat=40.9915,
        origin_lng=28.7971,
    )
    return Graph(
        meta=meta,
        nodes=[_node(n) for n in LAYOUT],
        edges=[_edge(a, b, k) for a, b, k in EDGES],
    )


@pytest.fixture
def store(graph: Graph) -> GraphStore:
    return GraphStore.from_graph(graph)


@pytest.fixture
def client(store: GraphStore) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]  # never read the local .env
        graph_source="unused",
        cors_origins="http://localhost:3000",
    )
    with TestClient(create_app(settings=settings, store=store)) as test_client:
        yield test_client


class FakeDatabase(Database):
    """In-memory stand-in for the Postgres layer (no network)."""

    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.similar_calls: list[str] = []

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def ping(self) -> bool:
        return self.healthy

    async def buildings(self, campus_only: bool) -> list[dict[str, Any]]:
        rows = [
            {"id": "w1", "code": "A", "name": "İstanbul Aydın Üniversitesi A Binası",
             "campus": True, "height_m": 9.6, "height_source": "default",
             "lng": 28.7972, "lat": 40.9917},
            {"id": "w2", "code": None, "name": None, "campus": False,
             "height_m": 6.4, "height_source": "default", "lng": 28.79, "lat": 40.99},
        ]  # fmt: skip
        return [r for r in rows if r["campus"] or not campus_only]

    async def similar_place_ids(self, key: str, limit: int) -> list[str]:
        self.similar_calls.append(key)
        return ["d"] if key.startswith("kut") else []


@pytest.fixture
def fake_db() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def db_client(store: GraphStore, fake_db: FakeDatabase) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        graph_source="unused",
    )
    app = create_app(settings=settings, store=store, database=fake_db)
    with TestClient(app) as test_client:
        yield test_client
