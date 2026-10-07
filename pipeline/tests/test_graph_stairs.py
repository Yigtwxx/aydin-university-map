from datetime import UTC, datetime

from amap_contracts.furniture import Stairs
from amap_contracts.graph import (
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
from amap_pipeline.export.furniture import build_furniture
from amap_pipeline.graph.stairs import climbs, mark_outdoor_stairs

FLIGHT = Stairs(
    id="f", foot=(0.0, 0.0), top=(0.0, 4.0), width_m=3.0, steps=12, rise_m=1.8
)


def test_an_edge_over_the_flight_climbs_it() -> None:
    assert climbs(FLIGHT, [(0.0, -3.0), (0.5, 7.0)])


def test_an_edge_along_the_foot_does_not() -> None:
    assert not climbs(FLIGHT, [(-5.0, 0.5), (5.0, 0.5)])  # both below the middle


def test_an_edge_beside_the_flight_does_not() -> None:
    assert not climbs(FLIGHT, [(4.0, -3.0), (4.0, 7.0)])


def _node(node_id: str, x: float, y: float) -> Node:
    return Node(
        id=node_id, kind=NodeKind.OUTDOOR, lat=40.99, lng=28.79, alt_m=1.6,
        enu=(x, y, 1.6), heading_deg=0.0, pose_source=PoseSource.SFM,
        label=LocalizedText(tr="Kampüs", en="Campus"),
        area=LocalizedText(tr="Kampüs", en="Campus"),
    )  # fmt: skip


def _edge(a: str, b: str) -> Edge:
    return Edge(
        id=f"{a}|{b}", source=a, target=b, kind=EdgeKind.OUTDOOR,
        origin=EdgeOrigin.TOUR, length_m=10.0, cost_s=8.0,
        length_source=LengthSource.SFM,
    )  # fmt: skip


def test_graph_edges_over_a_flight_become_stairs() -> None:
    graph = Graph(
        meta=GraphMeta(
            generated_at=datetime(2026, 10, 7, tzinfo=UTC),
            run_id="t",
            origin_lat=40.9915,
            origin_lng=28.7971,
        ),
        nodes=[_node("lo", 0, -3), _node("hi", 0, 7), _node("side", 8, 7)],
        edges=[_edge("lo", "hi"), _edge("hi", "side")],
    )
    marked, changed = mark_outdoor_stairs(graph, [FLIGHT])
    assert changed == ["lo|hi"]
    kinds = {e.id: e.kind for e in marked.edges}
    assert kinds == {"lo|hi": EdgeKind.STAIRS, "hi|side": EdgeKind.OUTDOOR}
    assert mark_outdoor_stairs(graph, []) == (graph, [])


def test_notebook_evidence_stays_out_of_the_export() -> None:
    collection = build_furniture(
        {
            "stairs": [
                {
                    "id": "f",
                    "foot": [0.0, 0.0],
                    "top": [0.0, 4.0],
                    "width_m": 3.0,
                    "steps": 12,
                    "rise_m": 1.8,
                    "evidence": [{"scene": "scene_1", "ath": 10.0}],
                }
            ],
            "seating": [
                {
                    "id": "terrace",
                    "outline": [[0, 0], [4, 0], [4, 3]],
                    "tables": 6,
                    "poi": "starbucks",
                }
            ],
        }
    )
    assert collection.stairs[0].railings == "none"
    assert collection.seating[0].poi == "starbucks"
