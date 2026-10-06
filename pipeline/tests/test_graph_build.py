from typing import Any

import pytest
from shapely.geometry import LineString, Point, Polygon

from amap_contracts.graph import EdgeKind, EdgeOrigin
from amap_pipeline.graph.build import (
    GraphParams,
    blocked_edges,
    build_graph,
    building_of,
    components,
    summarise,
)

# Local metres (x east, y north). A building blocks the way from b to f.
BUILDING = Polygon([(0, -14), (16, -14), (16, -6), (0, -6)])
POSITIONS = {
    "a": (0.0, 0.0, "outdoor"),
    "b": (8.0, 0.0, "outdoor"),
    "c": (16.0, 0.0, "outdoor"),
    "d": (100.0, 0.0, "outdoor"),  # teleport target
    "e": (8.0, -7.0, "entrance"),  # a metre inside the north wall (SfM vs OSM)
    "f": (8.0, -20.0, "outdoor"),  # behind the building
    "g": (4.0, 4.0, "outdoor"),  # not linked in the tour
}
LINKS = {"a": ["b", "d"], "b": ["a", "c", "e", "f"], "c": ["b"], "d": ["a"]}


def _posed() -> dict[str, dict[str, Any]]:
    return {
        s: {
            "lat": 40.99,
            "lng": 28.79,
            "x": x,
            "y": y,
            "height_m": 1.6,
            "heading_deg": 0,
        }
        for s, (x, y, _) in POSITIONS.items()
    }


def _scenes() -> dict[str, dict[str, Any]]:
    label = {"tr": "B Blok Giriş", "en": "B Block Entrance"}
    return {
        s: {
            "kind": kind,
            "label": label if kind == "entrance" else {"tr": "Kampüs", "en": "Campus"},
            "area": {"tr": "Florya Kampüs", "en": "Florya Campus"},
            "links": LINKS.get(s, []),
        }
        for s, (_, _, kind) in POSITIONS.items()
    }


@pytest.fixture
def built() -> tuple[Any, Any]:
    return build_graph(
        _posed(), _scenes(), BUILDING, run_id="test", params=GraphParams()
    )


def test_build_graph_keeps_walkable_tour_links(built: tuple[Any, Any]) -> None:
    graph, _ = built
    tour = {e.id for e in graph.edges if e.origin is EdgeOrigin.TOUR}
    assert tour == {"a|b", "b|c", "b|e", "b|f"}, f"Got {tour}"


def test_build_graph_drops_teleports(built: tuple[Any, Any]) -> None:
    _, report = built
    assert report.dropped["teleport"] == ["a|d"], f"Got {report.dropped}"


def test_build_graph_walks_around_buildings(built: tuple[Any, Any]) -> None:
    graph, report = built
    edge = next(e for e in graph.edges if e.id == "b|f")
    assert "b|f" in report.detoured, f"Got {report.detoured}"
    assert edge.path_enu is not None and len(edge.path_enu) > 2
    assert edge.path_enu[0] == (8.0, 0.0) and edge.path_enu[-1] == (8.0, -20.0)
    line = LineString(edge.path_enu)
    assert line.intersection(BUILDING).length < 0.01, "Detour cuts the building"
    assert edge.length_m == pytest.approx(line.length, rel=1e-3)
    assert blocked_edges(graph, BUILDING) == []


def test_build_graph_drops_unreasonable_detours() -> None:
    params = GraphParams(max_detour_ratio=1.1, max_detour_extra_m=0.0)
    graph, report = build_graph(_posed(), _scenes(), BUILDING, "test", params)
    assert "b|f" in report.dropped["crosses_building"], f"Got {report.dropped}"
    assert "b|f" not in {e.id for e in graph.edges}


def test_build_graph_moves_nodes_out_of_buildings(built: tuple[Any, Any]) -> None:
    graph, report = built
    entrance = next(n for n in graph.nodes if n.id == "e")
    assert set(report.snapped) == {"e"}, f"Got {report.snapped}"
    assert not BUILDING.contains(Point(entrance.enu[0], entrance.enu[1]))
    assert BUILDING.exterior.distance(Point(entrance.enu[0], entrance.enu[1])) < 1.5


def test_build_graph_doorway_link_is_entrance_kind(built: tuple[Any, Any]) -> None:
    graph, _ = built
    edge = next(e for e in graph.edges if e.id == "b|e")
    assert edge.kind is EdgeKind.ENTRANCE, f"Got {edge.kind}"


def test_build_graph_infers_line_of_sight_neighbours(built: tuple[Any, Any]) -> None:
    graph, _ = built
    inferred = {e.id for e in graph.edges if e.origin is EdgeOrigin.INFERRED}
    assert {"a|g", "b|g"} <= inferred, f"Got {inferred}"
    assert "e|f" not in inferred, "Inferred links must not cross buildings"


def test_build_graph_edge_lengths_are_metric(built: tuple[Any, Any]) -> None:
    graph, _ = built
    edge = next(e for e in graph.edges if e.id == "a|b")
    assert edge.length_m == pytest.approx(8.0), f"Got {edge.length_m}"
    assert edge.cost_s == pytest.approx(8.0 / 1.3), f"Got {edge.cost_s}"


def test_components_and_summary_report_isolated_nodes(built: tuple[Any, Any]) -> None:
    graph, report = built
    sizes = [len(c) for c in components(graph)]
    # f joins through its detour; only the teleport target d is cut off.
    assert sizes == [6, 1], f"Got {sizes}"
    summary = summarise(graph, report)
    assert summary["dropped"]["teleport"] == 1, f"Got {summary}"


@pytest.mark.parametrize(
    ("label", "expected"),
    [("A Blok Girişi", "A"), ("G-H Blok Giriş", "G-H"), ("Kampüs", None)],
)
def test_building_of_label_extracts_block(label: str, expected: str | None) -> None:
    assert building_of(label) == expected
