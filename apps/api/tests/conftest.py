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


# --- Indoor: spots without a measured position, hung off two entrances ------
# (x, y, kind, label tr, label en, building, floor, anchor, area)
# Measured: x, y, kind, label tr, label en, building, floor.
MEASURED: dict[str, tuple[Any, ...]] = {
    "gate": (0, 0, NodeKind.OUTDOOR, "Kampüs Girişi", "Campus Entrance", None, None),
    "yard": (0, 40, NodeKind.OUTDOOR, "Kampüs", "Campus", None, None),
    "m": (40, 40, NodeKind.ENTRANCE, "M Blok Giriş", "M Block Entrance", "M", 0),
    "x": (100, 40, NodeKind.ENTRANCE, "D Blok Giriş", "D Block Entrance", "D", 0),
}
# Indoor, standing at their anchor: anchor, label tr, label en, building, floor.
# Listed first, so the nearest node to a click on a door must skip them.
INDOOR_SPOTS: dict[str, tuple[Any, ...]] = {
    "m1": ("m", "M Blok -1.Kat", "M Block -1.Floor", "M", -1),
    "lab": ("m", "Anatomi Lab", "Anatomy Lab", "M", -1),
    "lab2": ("m", "Anatomi Lab", "Anatomy Lab", "M", -1),
    "m5": ("m", "M Blok -5 Koridor", "M Block -5 Corridor", "M", 5),
    "class_m": ("m", "Derslik", "Classroom", "M", 5),
    "p": ("m", "Geçit", "Passage", None, 0),
    "d0": ("x", "D Blok Giriş Kat", "D Block Entrance Floor", "D", 0),
    "d3": ("x", "D Blok 3.Kat", "D Block 3.Floor", "D", 3),
    "class_d": ("x", "Derslik", "Classroom", "D", 3),
}
INDOOR_AREAS = {"lab": "Sağlık Bilimleri", "lab2": "Sağlık Bilimleri"}
# A door SfM could not pose: an entrance at a borrowed position (no links).
INDOOR_DOORS = {"side": ("m", "M Blok Yan Giriş", "M Block Side Entrance", "M", 0)}
# (a, b, kind, length m, extra stairs seconds); m-x walks round a corner.
INDOOR_EDGES: list[tuple[str, str, EdgeKind, float, float]] = [
    ("gate", "yard", EdgeKind.OUTDOOR, 40.0, 0.0),
    ("m", "yard", EdgeKind.OUTDOOR, 40.0, 0.0),
    ("m", "x", EdgeKind.ENTRANCE, 90.0, 0.0),
    ("m", "m1", EdgeKind.STAIRS, 12.0, 15.0),
    ("lab", "m1", EdgeKind.INDOOR, 12.0, 0.0),
    ("lab", "lab2", EdgeKind.INDOOR, 12.0, 0.0),
    ("m", "m5", EdgeKind.STAIRS, 12.0, 75.0),
    ("class_m", "m5", EdgeKind.INDOOR, 12.0, 0.0),
    ("d0", "x", EdgeKind.ENTRANCE, 12.0, 0.0),
    ("d0", "d3", EdgeKind.STAIRS, 12.0, 45.0),
    ("class_d", "d3", EdgeKind.INDOOR, 12.0, 0.0),
    # A passage through a third building: shorter, but only an estimate.
    ("m", "p", EdgeKind.ENTRANCE, 12.0, 0.0),
    ("p", "x", EdgeKind.ENTRANCE, 60.0, 0.0),
    # A tour menu jump from the -1 corridor to the fifth floor's classroom.
    ("class_m", "m1", EdgeKind.STAIRS, 12.0, 90.0),
]  # fmt: skip


def _indoor_node(node_id: str) -> Node:
    if node_id in MEASURED:
        x, y, kind, tr, en, building, floor = MEASURED[node_id]
        anchor = None
    else:
        door = node_id in INDOOR_DOORS
        spot = INDOOR_DOORS[node_id] if door else INDOOR_SPOTS[node_id]
        anchor, tr, en, building, floor = spot
        x, y, *_ = MEASURED[anchor]
        kind = NodeKind.ENTRANCE if door else NodeKind.INDOOR
    area = INDOOR_AREAS.get(node_id, "Florya Kampüs")
    return Node(
        id=node_id,
        kind=kind,
        lat=40.9915 + y / 111_320.0,
        lng=28.7971 + x / 84_000.0,
        alt_m=1.6,
        enu=(float(x), float(y), 1.6),
        heading_deg=0.0,
        pose_source=PoseSource.INTERPOLATED if anchor else PoseSource.SFM,
        label=LocalizedText(tr=tr, en=en),
        area=LocalizedText(tr=area, en=area),
        building=building,
        floor=floor,
        anchor=anchor,
    )


@pytest.fixture
def indoor_store() -> GraphStore:
    nodes = [_indoor_node(n) for n in [*INDOOR_SPOTS, *INDOOR_DOORS, *MEASURED]]
    edges = [
        Edge(
            id="|".join(sorted((a, b))),
            source=min(a, b),
            target=max(a, b),
            kind=kind,
            origin=EdgeOrigin.TOUR,
            length_m=length,
            cost_s=length / WALKING_SPEED_MPS + stairs,
            length_source=(
                LengthSource.SFM
                if kind is EdgeKind.OUTDOOR or (a, b) == ("m", "x")
                else LengthSource.ESTIMATE
            ),
            path_enu=[(40.0, 40.0), (70.0, 70.0), (100.0, 40.0)]
            if (a, b) == ("m", "x")
            else None,
            # p stands at m: through a building; class_m-m1: a menu jump.
            passage=(a, b) in {("p", "x"), ("class_m", "m1")},
        )
        for a, b, kind, length, stairs in INDOOR_EDGES
    ]
    meta = GraphMeta(
        generated_at=datetime(2026, 10, 6, tzinfo=UTC),
        run_id="test",
        origin_lat=40.9915,
        origin_lng=28.7971,
    )
    return GraphStore.from_graph(Graph(meta=meta, nodes=nodes, edges=edges))


@pytest.fixture
def indoor_client(indoor_store: GraphStore) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        graph_source="unused",
    )
    with TestClient(create_app(settings=settings, store=indoor_store)) as client:
        yield client
