"""Spots up on a raised walkway walk along it, and down only by its landing."""

from datetime import UTC, datetime
from typing import Any

from shapely.geometry import LineString, Polygon

from amap_contracts.furniture import FurnitureCollection, Ramp, Stairs
from amap_contracts.graph import EdgeKind
from amap_pipeline.graph.barriers import build_barriers
from amap_pipeline.graph.build import GraphParams, build_graph, deck_line, walking_area
from amap_pipeline.graph.stairs import changes_level, mark_outdoor_stairs

# Local metres (x east, y north). Street level everywhere, a fence along
# y = 10; a footbridge 5 m up over it (x 0..4, y 0..20), reached from the
# street south of the fence by a flight whose top meets its south end.
FENCE = {"id": "fence", "line": [(-50.0, 10.0), (50.0, 10.0)], "height_m": 2.0}
BRIDGE = {
    "id": "bridge",
    "outline": [(0.0, 0.0), (4.0, 0.0), (4.0, 20.0), (0.0, 20.0)],
    "z_m": 5.0,
    "spots": ["up_s", "up_n"],
}
LANDING = {
    "id": "landing",
    "foot": (2.0, -8.0),
    "top": (2.0, -0.5),
    "width_m": 2.0,
    "steps": 30,
    "rise_m": 5.0,
}
BALUSTRADE = {
    "id": "balustrade",
    "line": [(0.0, 0.0), (0.0, 20.0)],
    "height_m": 1.1,
    "base_z": 5.0,
}
NOWHERE = Polygon([(500, 500), (501, 500), (501, 501), (500, 501)])
SPOTS = {
    "up_s": (2.0, 2.0),
    "up_n": (2.0, 18.0),
    "street_s": (8.0, -8.0),
    "street_n": (8.0, 18.0),
    "street_w": (-6.0, 2.0),
    "street_e": (10.0, 2.0),
}


def _furniture(landing: bool = True, **extra: Any) -> FurnitureCollection:
    return FurnitureCollection.model_validate(
        {
            "generated_at": datetime.now(UTC),
            "railings": [FENCE, *extra.get("railings", [])],
            "walkways": extra.get("walkways", [BRIDGE]),
            "stairs": [LANDING] if landing else [],
        }
    )


def _graph(
    links: dict[str, list[str]], furniture: FurnitureCollection | None = None
) -> tuple[Any, Any, FurnitureCollection]:
    furniture = furniture if furniture is not None else _furniture()
    posed = {
        s: {
            "lat": 40.99,
            "lng": 28.79,
            "x": x,
            "y": y,
            "height_m": 1.6,
            "heading_deg": 0,
        }
        for s, (x, y) in SPOTS.items()
    }
    scenes = {
        s: {
            "kind": "outdoor",
            "label": {"tr": "Kampüs", "en": "Campus"},
            "area": {"tr": "Florya Kampüs", "en": "Florya Campus"},
            "links": links.get(s, []),
        }
        for s in SPOTS
    }
    graph, report = build_graph(
        posed,
        scenes,
        NOWHERE,
        "test",
        params=GraphParams(indoor=False, infer_radius_m=0.1),
        barriers=build_barriers(furniture),
    )
    return graph, report, furniture


def test_build_barriers_walkway_becomes_a_deck_with_its_landing() -> None:
    barriers = build_barriers(_furniture())
    assert [d.id for d in barriers.decks] == ["bridge"], barriers.decks
    deck = barriers.decks[0]
    assert [f.id for f in deck.landings] == ["landing"], deck.landings
    assert deck.spots == {"up_s", "up_n"}, deck.spots
    assert deck.floor.covers(LineString([(2.0, 0.0), (2.0, 20.0)]))


def test_build_barriers_flight_to_another_height_is_no_landing() -> None:
    low = {**LANDING, "rise_m": 2.0}
    furniture = FurnitureCollection.model_validate(
        {"generated_at": datetime.now(UTC), "walkways": [BRIDGE], "stairs": [low]}
    )
    assert build_barriers(furniture).decks[0].landings == ()


def test_build_barriers_walkway_balustrade_is_no_ground_barrier() -> None:
    barriers = build_barriers(_furniture(railings=[BALUSTRADE]))
    assert not barriers.hard.intersects(LineString([(-1.0, 5.0), (1.0, 5.0)])), (
        "a balustrade up on the bridge blocked the street below"
    )
    assert barriers.hard.intersects(LineString([(-5.0, 9.0), (-5.0, 11.0)]))


def test_build_graph_deck_walk_ignores_the_fence_below() -> None:
    graph, report, _ = _graph({"up_s": ["up_n"]})
    edge = next(e for e in graph.edges if e.id == "up_n|up_s")
    assert edge.crosses is None, edge.crosses
    assert report.barrier_fallback == [], report.barrier_fallback


def test_build_graph_deck_to_street_goes_down_the_landing() -> None:
    graph, report, furniture = _graph({"up_n": ["street_s"]})
    edge = next(e for e in graph.edges if e.id == "street_s|up_n")
    assert edge.path_enu is not None, "went straight off the bridge"
    path = [tuple(p) for p in edge.path_enu]
    assert (2.0, -0.5) in path and (2.0, -8.0) in path, path
    assert edge.crosses is None, edge.crosses
    marked, _ = mark_outdoor_stairs(graph, furniture.stairs)
    kind = next(e for e in marked.edges if e.id == edge.id).kind
    assert kind is EdgeKind.STAIRS, kind
    assert report.dropped["off_deck"] == [], report.dropped


def test_build_graph_deck_to_street_without_landing_is_dropped() -> None:
    graph, report, _ = _graph({"up_n": ["street_s"]}, _furniture(landing=False))
    assert "street_s|up_n" not in {e.id for e in graph.edges}
    assert report.dropped["off_deck"] == ["street_s|up_n"], report.dropped


def test_build_graph_street_beyond_the_fence_is_not_reached_over_the_deck() -> None:
    # The landing comes down south of the fence: north of it is another walk.
    graph, report, _ = _graph({"up_n": ["street_n"]})
    assert "street_n|up_n" not in {e.id for e in graph.edges}
    assert report.dropped["off_deck"] == ["street_n|up_n"], report.dropped


def test_build_graph_street_link_passes_under_the_deck_spot() -> None:
    graph, report, _ = _graph({"street_w": ["street_e"]})  # right under up_s
    assert report.passed_by == [], "split at a spot up on the bridge"
    assert "street_e|street_w" in {e.id for e in graph.edges}


def test_deck_line_two_walkways_that_do_not_meet_have_no_walk() -> None:
    other = {
        "id": "other",
        "outline": [(30.0, 0.0), (34.0, 0.0), (34.0, 20.0), (30.0, 20.0)],
        "z_m": 5.0,
        "spots": ["street_n"],
    }
    barriers = build_barriers(_furniture(walkways=[BRIDGE, other]))
    graph, _, _ = _graph({}, _furniture(walkways=[BRIDGE, other]))
    by_id = {n.id: n for n in graph.nodes}
    decks = {s: d for d in barriers.decks for s in d.spots}
    area = walking_area(NOWHERE, barriers)
    walk = deck_line(by_id["up_n"], by_id["street_n"], decks, area, GraphParams())
    assert walk is None, walk


def test_changes_level_side_climb_over_a_flight_is_stairs() -> None:
    flight = Stairs.model_validate(LANDING)
    side = [(-4.0, -2.0), (6.0, -2.0)]  # across the flight, not along it
    assert changes_level(side, (0.0, 5.0), [flight])
    assert not changes_level(side, (0.0, 0.2), [flight]), "a kerb is no climb"
    assert not changes_level(side, (None, 5.0), [flight]), "unknown height"
    ramp = Ramp.model_validate({**LANDING, "id": "ramp", "foot": (0.0, -8.0)})
    assert not changes_level(side, (0.0, 5.0), [flight], [ramp]), (
        "a ramp beside the flight carries the climb"
    )
