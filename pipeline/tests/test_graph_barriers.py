"""Walking lines keep out of walls, railings, hedges and café seating."""

from datetime import UTC, datetime
from typing import Any

import pytest
from shapely.geometry import LineString, Point, Polygon

from amap_contracts.furniture import FurnitureCollection
from amap_contracts.graph import EdgeCrossing, EdgeKind, EdgeOrigin
from amap_pipeline.export.furniture import build_furniture, read_furniture
from amap_pipeline.graph.barriers import (
    Barriers,
    build_barriers,
    item_footprint,
    opening,
    wall_lines,
)
from amap_pipeline.graph.build import GraphParams, build_graph
from amap_pipeline.graph.clearance import Obstacles, snap_point, walk_around
from amap_pipeline.graph.stairs import mark_outdoor_stairs

# Local metres (x east, y north). A terrace 2 m up north of y = 10, climbed
# by a flight at x = 10; open ground (street level) to the south.
UPPER = [(0.0, 10.0), (20.0, 10.0), (20.0, 30.0), (0.0, 30.0)]
FLIGHT = {
    "id": "f",
    "foot": (10.0, 8.0),
    "top": (10.0, 10.5),
    "width_m": 2.0,
    "steps": 12,
    "rise_m": 2.0,
}
NOWHERE = Polygon([(500, 500), (501, 500), (501, 501), (500, 501)])


def _furniture(**groups: list[dict[str, Any]]) -> FurnitureCollection:
    return FurnitureCollection.model_validate(
        {"generated_at": datetime.now(UTC), **groups}
    )


def _terraced(stairs: bool = True) -> FurnitureCollection:
    return _furniture(
        terraces=[{"id": "upper", "outline": UPPER, "z_m": 2.0, "edge": "wall"}],
        stairs=[FLIGHT] if stairs else [],
    )


def _graph_inputs(
    positions: dict[str, tuple[float, float]], links: dict[str, list[str]]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    posed = {
        s: {
            "lat": 40.99,
            "lng": 28.79,
            "x": x,
            "y": y,
            "height_m": 1.6,
            "heading_deg": 0,
        }
        for s, (x, y) in positions.items()
    }
    scenes = {
        s: {
            "kind": "outdoor",
            "label": {"tr": "Kampüs", "en": "Campus"},
            "area": {"tr": "Florya Kampüs", "en": "Florya Campus"},
            "links": links.get(s, []),
        }
        for s in positions
    }
    return posed, scenes


def test_wall_lines_terrace_edge_is_a_wall() -> None:
    walls = wall_lines(_terraced().terraces)
    assert walls.length == pytest.approx(80.0), f"Got {walls.length}"


def test_wall_lines_kerb_height_step_is_not_a_wall() -> None:
    low = _furniture(
        terraces=[{"id": "kerb", "outline": UPPER, "z_m": 0.3, "edge": "wall"}]
    )
    assert wall_lines(low.terraces).is_empty


def test_wall_lines_between_level_siblings_is_open() -> None:
    # Two terraces at one level side by side: their shared edge is no wall.
    east = [(20.0, 10.0), (40.0, 10.0), (40.0, 30.0), (20.0, 30.0)]
    pair = _furniture(
        terraces=[
            {"id": "west", "outline": UPPER, "z_m": 2.0, "edge": "wall"},
            {"id": "east", "outline": east, "z_m": 2.0, "edge": "wall"},
        ]
    )
    shared = LineString([(20.0, 11.0), (20.0, 29.0)])
    assert wall_lines(pair.terraces).intersection(shared).length < 1e-6


def test_wall_lines_along_a_facade_fold_into_the_building() -> None:
    # The terrace edge runs 1 m off the building's south face: no wall there,
    # but the edge meeting the building head-on stays a wall.
    building = Polygon([(2.0, 11.0), (18.0, 11.0), (18.0, 20.0), (2.0, 20.0)])
    walls = wall_lines(_terraced().terraces, building)
    along = LineString([(4.0, 10.0), (16.0, 10.0)])
    assert walls.intersection(along).length < 1e-6, "facade strip kept as wall"
    assert walls.intersection(LineString([(0.0, 10.0), (0.0, 30.0)])).length > 19


def test_build_barriers_flight_opens_its_wall() -> None:
    barriers = build_barriers(_terraced())
    climb = LineString([FLIGHT["foot"], FLIGHT["top"]])
    assert not climb.intersects(barriers.hard), "the flight is walled off"
    beside = LineString([(4.0, 8.0), (4.0, 12.0)])
    assert beside.intersects(barriers.hard), "the wall beside the flight is open"


def test_build_barriers_notebook_flights_are_open() -> None:
    furniture = build_furniture(read_furniture())
    hard = build_barriers(furniture).hard
    blocked = [
        f.id
        for f in [*furniture.stairs, *furniture.ramps]
        if LineString([f.foot, f.top]).intersects(hard)
    ]
    assert blocked == [], f"flights or ramps walled off: {blocked}"


def test_opening_covers_the_flight_and_a_margin() -> None:
    gap = opening(build_furniture({"stairs": [FLIGHT]}).stairs[0])
    assert gap.contains(Point(10.0, 7.2)) and gap.contains(Point(10.0, 11.3))
    assert gap.contains(Point(11.2, 9.0)) and not gap.contains(Point(11.5, 9.0))


def test_item_footprint_hedge_runs_across_its_heading() -> None:
    hedge = _furniture(
        items=[{"id": "h", "kind": "hedge", "at": (0.0, 0.0), "length_m": 4.0}]
    ).items[0]
    footprint = item_footprint(hedge)
    assert footprint is not None
    minx, miny, maxx, maxy = footprint.bounds
    # Heading 0 faces north: the hedge runs east-west.
    assert (maxx - minx, maxy - miny) == pytest.approx((4.0, 0.62))


def test_item_footprint_lamp_is_ignored() -> None:
    lamp = _furniture(items=[{"id": "l", "kind": "lamp", "at": (0.0, 0.0)}]).items[0]
    assert item_footprint(lamp) is None


def test_obstacles_railing_survives_the_graze_shrink() -> None:
    rail = build_barriers(
        _furniture(railings=[{"id": "r", "line": [(-5.0, 0.0), (5.0, 0.0)]}])
    )
    obstacles = Obstacles.of(NOWHERE, rail.hard)
    assert obstacles.crosses((0.0, -2.0), (0.0, 2.0)), "the railing was lost"


def test_walk_around_passes_the_fence_at_its_gate() -> None:
    fence = build_barriers(
        _furniture(
            railings=[
                {"id": "w", "line": [(-40.0, 0.0), (-2.0, 0.0)], "style": "fence"},
                {"id": "e", "line": [(2.0, 0.0), (40.0, 0.0)], "style": "fence"},
            ]
        )
    )
    obstacles = Obstacles.of(NOWHERE, fence.hard)
    path = walk_around((-10.0, -8.0), (-10.0, 8.0), obstacles)
    assert path is not None and len(path) > 2
    crossing = LineString(path).intersection(LineString([(-40, 0), (40, 0)]))
    assert -2.0 < crossing.x < 2.0, f"crossed the fence at {crossing}"


def test_snap_point_stays_on_its_side_of_the_fence() -> None:
    # A building against the fence: a node a metre inside its south wall
    # (just north of the fence) must land north of it, not on the street.
    building = Polygon([(-10.0, 0.5), (10.0, 0.5), (10.0, 4.0), (-10.0, 4.0)])
    fence = build_barriers(
        _furniture(railings=[{"id": "f", "line": [(-30.0, 0.0), (30.0, 0.0)]}])
    )
    x, y = snap_point((0.0, 1.0), Obstacles.of(building, fence.hard))
    assert y > 0.0, f"snapped across the fence to {(x, y)}"
    assert not building.contains(Point(x, y))


def test_build_graph_climbs_by_the_flight() -> None:
    posed, scenes = _graph_inputs({"s": (3.0, 0.0), "n": (3.0, 20.0)}, {"s": ["n"]})
    furniture = _terraced()
    graph, report = build_graph(
        posed, scenes, NOWHERE, "test", barriers=build_barriers(furniture)
    )
    edge = next(e for e in graph.edges if e.id == "n|s")
    assert edge.path_enu is not None, "the tour link went straight up the wall"
    line = LineString(edge.path_enu)
    assert not line.intersects(build_barriers(furniture).hard)
    assert report.barrier_fallback == [], report.barrier_fallback
    marked, _ = mark_outdoor_stairs(graph, furniture.stairs)
    assert next(e for e in marked.edges if e.id == "n|s").kind is EdgeKind.STAIRS


def test_build_graph_wall_without_flight_keeps_the_tour_walk_and_reports_it() -> None:
    posed, scenes = _graph_inputs(
        {"s": (3.0, 0.0), "n": (3.0, 20.0), "m": (6.0, 20.0)}, {"s": ["n"]}
    )
    barriers = build_barriers(_terraced(stairs=False))
    graph, report = build_graph(posed, scenes, NOWHERE, "test", barriers=barriers)
    ids = {e.id for e in graph.edges}
    assert "n|s" in ids, "a walk the tour proves must stay"
    assert report.barrier_fallback == ["n|s"], report.barrier_fallback
    inferred = {e.id for e in graph.edges if e.origin is EdgeOrigin.INFERRED}
    assert "m|s" not in inferred, "an inferred link must never cross a wall"


def test_build_graph_walks_round_a_hedge() -> None:
    posed, scenes = _graph_inputs({"a": (0.0, 0.0), "b": (0.0, 10.0)}, {"a": ["b"]})
    hedge = {"id": "h", "kind": "hedge", "at": (0.0, 5.0), "length_m": 3.0}
    barriers = build_barriers(_furniture(items=[hedge]))
    graph, report = build_graph(posed, scenes, NOWHERE, "test", barriers=barriers)
    edge = next(e for e in graph.edges if e.id == "a|b")
    assert edge.path_enu is not None and len(edge.path_enu) > 2
    assert not LineString(edge.path_enu).intersects(barriers.soft)
    assert report.soft_fallback == [], report.soft_fallback


def test_build_graph_crosses_seating_only_without_a_walk_round() -> None:
    # Café seating fills the lane between two buildings: the tour link goes
    # through (people walk between the tables) and is reported.
    west = Polygon([(-30.0, -5.0), (-3.0, -5.0), (-3.0, 15.0), (-30.0, 15.0)])
    east = Polygon([(3.0, -5.0), (30.0, -5.0), (30.0, 15.0), (3.0, 15.0)])
    seating = [(-3.0, 3.0), (3.0, 3.0), (3.0, 7.0), (-3.0, 7.0)]
    barriers = build_barriers(
        _furniture(seating=[{"id": "c", "outline": seating, "tables": 4}])
    )
    posed, scenes = _graph_inputs({"a": (0.0, -10.0), "b": (0.0, 20.0)}, {"a": ["b"]})
    graph, report = build_graph(
        posed, scenes, west.union(east), "test", barriers=barriers
    )
    assert "a|b" in {e.id for e in graph.edges}
    assert report.soft_fallback == ["a|b"], report.soft_fallback


def test_build_graph_node_among_tables_still_links_out() -> None:
    seating = [(-3.0, -3.0), (3.0, -3.0), (3.0, 3.0), (-3.0, 3.0)]
    barriers = build_barriers(
        _furniture(seating=[{"id": "c", "outline": seating, "tables": 4}])
    )
    posed, scenes = _graph_inputs({"cafe": (0.0, 0.0), "out": (15.0, 0.0)}, {})
    graph, _ = build_graph(posed, scenes, NOWHERE, "test", barriers=barriers)
    assert "cafe|out" in {e.id for e in graph.edges}, "the café panorama is cut off"


def test_build_graph_without_barriers_is_unchanged() -> None:
    posed, scenes = _graph_inputs({"s": (3.0, 0.0), "n": (3.0, 20.0)}, {"s": ["n"]})
    graph, _ = build_graph(posed, scenes, NOWHERE, "test", barriers=Barriers.none())
    assert next(e for e in graph.edges if e.id == "n|s").path_enu is None
    assert GraphParams().soft_detour_ratio > 1.0


def test_build_graph_marks_lines_through_seating_and_over_walls() -> None:
    # Long seating south of the café spot (which stands by its north side);
    # tour links run north (out by its side), south (through every table)
    # and up the terrace wall west of the flight-less terrace.
    seating = [(-10.0, -3.0), (10.0, -3.0), (10.0, 3.0), (-10.0, 3.0)]
    upper = [(-40.0, 10.0), (-25.0, 10.0), (-25.0, 30.0), (-40.0, 30.0)]
    furniture = _furniture(
        terraces=[{"id": "upper", "outline": upper, "z_m": 2.0, "edge": "wall"}],
        seating=[{"id": "c", "outline": seating, "tables": 8}],
    )
    posed, scenes = _graph_inputs(
        {
            "cafe": (0.0, 2.5),
            "north": (0.0, 15.0),
            "south": (0.0, -15.0),
            "low": (-32.0, 0.0),
            "up": (-32.0, 20.0),
        },
        {"cafe": ["north", "south"], "low": ["up"]},
    )
    graph, _ = build_graph(
        posed, scenes, NOWHERE, "test", barriers=build_barriers(furniture)
    )
    crosses = {e.id: e.crosses for e in graph.edges}
    assert crosses["cafe|north"] is None, "leaving by the near side is clean"
    assert crosses["cafe|south"] is EdgeCrossing.SOFT, crosses
    assert crosses["low|up"] is EdgeCrossing.BARRIER, crosses


def test_build_graph_splits_a_tour_link_at_a_spot_it_walks_past() -> None:
    # The tour links a and c; b stands on the way (0.4 m off the line).
    posed, scenes = _graph_inputs(
        {"a": (0.0, 0.0), "b": (20.0, 0.4), "c": (40.0, 0.0)}, {"a": ["c"]}
    )
    graph, report = build_graph(
        posed, scenes, NOWHERE, "test", GraphParams(infer_radius_m=1.0)
    )
    ids = {e.id for e in graph.edges if e.origin is EdgeOrigin.TOUR}
    assert ids == {"a|b", "b|c"}, ids
    assert report.passed_by == ["a|c via b"], report.passed_by


def test_barriers_leaks_a_level_change_off_the_flight() -> None:
    # The terrace's south edge runs along a building's facade (folded into
    # it, no wall): a line slipping between them still changes level.
    building = Polygon([(12.0, 11.0), (18.0, 11.0), (18.0, 20.0), (12.0, 20.0)])
    ground = [(-50.0, -50.0), (50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)]
    furniture = _furniture(
        terraces=[
            {"id": "campus", "outline": ground, "z_m": 0.0, "edge": "slope"},
            {"id": "upper", "outline": UPPER, "z_m": 2.0, "edge": "wall"},
        ],
        stairs=[FLIGHT],
    )
    barriers = build_barriers(furniture, footprints=building)
    assert not barriers.leaks([(10.0, 0.0), (10.0, 20.0)]), "up the flight"
    assert barriers.leaks([(15.0, 0.0), (15.0, 10.5), (19.5, 25.0)])
    assert not barriers.leaks([(-5.0, 0.0), (-5.0, 20.0)]), "level ground"
