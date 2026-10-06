from typing import Any

import pytest
from shapely.geometry import Polygon

from amap_contracts.graph import EdgeKind, EdgeOrigin
from amap_pipeline.graph.build import (
    GraphParams,
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
    "e": (8.0, -10.0, "entrance"),  # inside the building edge: doorway pano
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
    assert tour == {"a|b", "b|c", "b|e"}, f"Got {tour}"


def test_build_graph_drops_teleports_and_building_crossings(
    built: tuple[Any, Any],
) -> None:
    _, report = built
    assert report.dropped["teleport"] == ["a|d"], f"Got {report.dropped}"
    assert report.dropped["crosses_building"] == ["b|f"], f"Got {report.dropped}"


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
    assert sizes[0] == 5 and sorted(sizes[1:]) == [1, 1], f"Got {sizes}"
    summary = summarise(graph, report)
    assert summary["dropped"]["teleport"] == 1, f"Got {summary}"


@pytest.mark.parametrize(
    ("label", "expected"),
    [("A Blok Girişi", "A"), ("G-H Blok Giriş", "G-H"), ("Kampüs", None)],
)
def test_building_of_label_extracts_block(label: str, expected: str | None) -> None:
    assert building_of(label) == expected
