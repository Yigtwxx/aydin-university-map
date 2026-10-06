"""Indoor nodes hung off the walking graph through tour links (synthetic)."""

import json
import math
from typing import Any

import pytest
from shapely.geometry import Polygon

from amap_contracts.graph import (
    WALKING_SPEED_MPS,
    EdgeKind,
    Graph,
    LengthSource,
    NodeKind,
    PoseSource,
)
from amap_pipeline.graph.build import (
    GraphParams,
    blocked_edges,
    build_graph,
    step_free_conflicts,
)
from amap_pipeline.graph.indoor import INDOOR_LINK_M, STAIRS_S_PER_FLOOR

# A building between the M Blok door and the far gate x.
BUILDING = Polygon([(30, -5), (50, -5), (50, 5), (30, 5)])
# Measured (posed) scenes: x east, y north, kind, label, area.
POSED: dict[str, tuple[float, float, str, str, str]] = {
    "g": (0.0, 0.0, "outdoor", "Kampüs", "Florya Kampüs"),
    "m": (20.0, 0.0, "entrance", "M Blok Giriş", "M Blok"),
    "k": (20.0, 30.0, "entrance", "Kütüphane Giriş", "Kütüphane"),
    "x": (80.0, 0.0, "outdoor", "Kampüs", "Florya Kampüs"),
    "z": (20.0, -30.0, "entrance", "Acil Giriş", "Tıp Fakültesi Hastanesi"),
}
# Unposed scenes: kind, label, area, links.
UNPOSED: dict[str, tuple[str, str, str, list[str]]] = {
    "m1": ("indoor", "M Blok -1.Kat", "0", ["m", "m1a"]),
    "m1a": ("indoor", "Anestezi Lab.", "Sağlık Bilimleri", ["m1"]),
    "m5": ("indoor", "M Blok -5 Koridor", "M Blok-5.K", ["m", "m5a"]),
    "m5a": ("indoor", "Anatomi Lab", "Sağlık Bilimleri", ["m5"]),
    # A corridor linked from two doors hangs off the nearer-ranked one.
    "c": ("indoor", "Koridor", "Kampüs", ["k", "m"]),
    # T Blok: an unposed door off the far gate; a foyer between two floors.
    "te": ("entrance", "T Blok Giriş", "T Blok", ["x", "f1", "m"]),
    "f1": ("indoor", "T Blok Fuaye", "T Blok", ["te", "f2", "t2"]),
    "f2": ("indoor", "T Blok Fuaye", "T Blok", ["f1", "tm1"]),
    "t2": ("indoor", "T Blok 2.Kat", "T Blok", ["f1", "t3"]),
    # A tour menu jump: T Blok 3.Kat to a library basement, four floors down.
    "t3": ("indoor", "T Blok 3.Kat", "T Blok", ["t2", "lib"]),
    "lib": ("indoor", "Okuma Salonu", "Kütüphane 1.Bodrum", ["t3"]),
    "tm1": ("indoor", "T Blok -1.Kat", "T Blok", ["f2"]),
    "room": ("indoor", "Kantin", "T Blok", ["f2"]),
    # Doors SfM could not pose: one in the library's area, one in the
    # hospital's (it hangs off the hospital, though "k" < "z").
    "kd": ("entrance", "Kütüphane Yan Giriş", "Kütüphane", ["k", "m"]),
    "th": (
        "entrance",
        "Tıp Fakültesi Hastanesi Giriş",
        "Tıp Fakültesi Hastanesi",
        ["k", "z"],
    ),
    # Not reachable: no link, or only through an unposed outdoor spot.
    "lone": ("indoor", "Depo", "Florya Kampüs", []),
    "yard": ("outdoor", "T Blok Bahçe", "T Blok", ["m1", "far"]),
    "far": ("indoor", "Sera", "T Blok", ["yard"]),
}
YAWS = {"m1": {"m": 300.0, "m1a": 10.0}, "m": {"m5": 95.5}}


def _scenes() -> dict[str, dict[str, Any]]:
    links: dict[str, set[str]] = {s: set() for s in [*POSED, *UNPOSED]}
    for name, (*_, linked) in UNPOSED.items():
        for other in linked:
            links[name].add(other)
            links[other].add(name)
    links["g"] |= {"m", "k", "z"}
    for name in ("m", "k", "z"):
        links[name].add("g")
    scenes: dict[str, dict[str, Any]] = {}
    for name, (_, _, kind, label, area) in POSED.items():
        scenes[name] = {"kind": kind, "label": label, "area": area}
    for name, (kind, label, area, _) in UNPOSED.items():
        scenes[name] = {"kind": kind, "label": label, "area": area}
    return {
        name: {
            "kind": s["kind"],
            "label": {"tr": s["label"], "en": f"{s['label']} (en)"},
            "area": {"tr": s["area"], "en": f"{s['area']} (en)"},
            "links": sorted(links[name]),
            "link_yaw": YAWS.get(name, {}),
        }
        for name, s in scenes.items()
    }


def _posed() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "lat": 40.99 + y / 111_320.0,
            "lng": 28.79 + x / 84_000.0,
            "x": x,
            "y": y,
            "height_m": 1.6,
            "heading_deg": 0.0,
        }
        for name, (x, y, *_) in POSED.items()
    }


@pytest.fixture
def graph() -> Graph:
    built, _ = build_graph(_posed(), _scenes(), BUILDING, "test", GraphParams())
    return built


def _node(graph: Graph, node_id: str) -> Any:
    return next(n for n in graph.nodes if n.id == node_id)


def _edge(graph: Graph, a: str, b: str) -> Any:
    key = "|".join(sorted((a, b)))
    return next(e for e in graph.edges if e.id == key)


def test_attach_indoor_linked_scenes_become_approximate_nodes(graph: Graph) -> None:
    ids = {n.id for n in graph.nodes if n.approximate}
    expected = {"m1", "m1a", "m5", "m5a", "c", "te", "f1", "f2", "t2", "tm1", "room"}
    expected |= {"kd", "th", "t3", "lib"}
    assert ids == expected, f"Got {sorted(ids)}"
    left_out = {"lone", "yard", "far"} & {n.id for n in graph.nodes}
    assert not left_out, f"unlinked or behind an unposed open area: {left_out}"


def test_attach_indoor_position_is_borrowed_from_anchor(graph: Graph) -> None:
    door = _node(graph, "m")
    lab = _node(graph, "m1a")
    assert lab.anchor == "m", f"Got {lab.anchor}"
    assert (lab.enu, lab.lat, lab.lng) == (door.enu, door.lat, door.lng), lab
    assert lab.pose_source is PoseSource.INTERPOLATED, lab.pose_source
    assert _node(graph, "te").anchor == "x", "not M Blok's door: another block"
    assert _node(graph, "f1").anchor == "x", "chains inherit the anchor"
    assert _node(graph, "te").kind is NodeKind.ENTRANCE, "unposed doors stay doors"


def test_attach_indoor_floor_comes_from_label_area_or_corridor(graph: Graph) -> None:
    floors = {n.id: n.floor for n in graph.nodes}
    # A hyphen right before the digit is a basement: "M Blok -5 Koridor" is -5.
    assert floors["m1"] == -1 and floors["m5"] == -5, floors
    assert floors["m1a"] == -1 and floors["m5a"] == -5, "rooms off a floor's corridor"
    assert floors["f1"] is None and floors["f2"] is None, "a landing between floors"
    assert floors["room"] is None, "nothing is carried through a landing"
    assert floors["te"] == 0 and floors["m"] == 0 and floors["k"] == 0, "doors: 0"
    assert floors["g"] is None, "open areas have no floor"


def test_attach_indoor_building_is_labelled_or_inherited(graph: Graph) -> None:
    assert _node(graph, "m1a").building == "M", "inherited from M Blok -1.Kat"
    assert _node(graph, "te").building == "T", "labelled"
    assert _node(graph, "c").anchor == "k", "two doors, no block: the smallest id"


def test_attach_indoor_floor_change_is_a_stairs_estimate(graph: Graph) -> None:
    stairs = _edge(graph, "m", "m1")
    assert stairs.kind is EdgeKind.STAIRS, f"Got {stairs.kind}"
    assert stairs.length_m == pytest.approx(INDOOR_LINK_M)
    assert stairs.cost_s == pytest.approx(
        INDOOR_LINK_M / WALKING_SPEED_MPS + STAIRS_S_PER_FLOOR
    )
    up = _edge(graph, "m", "m5")
    assert up.cost_s == pytest.approx(
        INDOOR_LINK_M / WALKING_SPEED_MPS + 5 * STAIRS_S_PER_FLOOR
    )
    room = _edge(graph, "m1", "m1a")
    assert room.kind is EdgeKind.INDOOR, f"Got {room.kind}"
    assert room.length_source is LengthSource.ESTIMATE, f"Got {room.length_source}"
    assert _edge(graph, "te", "x").kind is EdgeKind.ENTRANCE, "through a doorway"


def test_attach_indoor_edge_never_shorter_than_straight_line(graph: Graph) -> None:
    by_id = {n.id: n for n in graph.nodes}
    for edge in graph.edges:
        a, b = by_id[edge.source], by_id[edge.target]
        assert edge.length_m >= math.dist(a.enu, b.enu) - 1e-6, edge.id
    far_door = _edge(graph, "c", "m")  # c stands at k, 30 m from m
    assert far_door.length_m == pytest.approx(30.0)


def test_attach_indoor_edge_carries_hotspot_yaws(graph: Graph) -> None:
    edge = _edge(graph, "m", "m1")  # source m, target m1
    assert (edge.source_yaw_deg, edge.target_yaw_deg) == (None, 300.0)
    assert _edge(graph, "m1", "m1a").source_yaw_deg == 10.0
    assert _edge(graph, "m", "m5").source_yaw_deg == 95.5


def test_blocked_edges_borrowed_positions_are_exempt(graph: Graph) -> None:
    # te stands at x: its link to m would be a straight line through BUILDING.
    door = _edge(graph, "m", "te")
    assert door.kind is EdgeKind.ENTRANCE and door.length_m == pytest.approx(60.0)
    assert door.passage, "no reasonable walk outside: a passage, never drawn"
    assert blocked_edges(graph, BUILDING) == [], "passages are exempt"


def test_blocked_edges_door_at_borrowed_position_is_checked(graph: Graph) -> None:
    edge = _edge(graph, "m", "te").model_copy(update={"passage": False})
    edges = [edge if e.id == edge.id else e for e in graph.edges]
    blocked = blocked_edges(graph.model_copy(update={"edges": edges}), BUILDING)
    assert blocked == ["m|te"], f"only one position is exempt: {blocked}"


def test_build_graph_indoor_off_keeps_outdoor_graph() -> None:
    graph, report = build_graph(
        _posed(), _scenes(), BUILDING, "test", GraphParams(indoor=False)
    )
    assert not any(n.approximate for n in graph.nodes), "no indoor nodes"
    assert report.indoor.nodes == 0, f"Got {report.indoor.nodes}"
    assert {n.floor for n in graph.nodes} == {None}, "outdoor graph untouched"


def test_build_graph_indoor_report_lists_unreachable_rooms() -> None:
    _, report = build_graph(_posed(), _scenes(), BUILDING, "test", GraphParams())
    assert report.indoor.unreachable == ["far", "lone"], report.indoor.unreachable
    assert report.indoor.floors == {"labelled": 9, "carried": 2, "unknown": 4}


def test_build_graph_indoor_export_is_deterministic() -> None:
    def export() -> str:
        graph, _ = build_graph(_posed(), _scenes(), BUILDING, "test", GraphParams())
        data = graph.to_geojson()
        data["meta"].pop("generated_at")
        return json.dumps(data, sort_keys=True)

    assert export() == export()


def test_attach_indoor_landing_still_pays_for_its_flights(graph: Graph) -> None:
    # f1 (unknown floor) joins the door (0) and T Blok 2.Kat: halfway, 1.
    up = _edge(graph, "f1", "te").cost_s + _edge(graph, "f1", "t2").cost_s
    walk = 2 * INDOOR_LINK_M / WALKING_SPEED_MPS
    assert up == pytest.approx(walk + 2 * STAIRS_S_PER_FLOOR), f"Got {up}"
    assert _edge(graph, "f1", "t2").kind is EdgeKind.STAIRS, "a whole flight"
    assert _node(graph, "f1").floor is None, "the floor itself stays unknown"


def test_attach_indoor_same_area_door_beats_smaller_id(graph: Graph) -> None:
    assert _node(graph, "th").anchor == "z", "the hospital's door, not the library"
    assert _node(graph, "kd").anchor == "k", "the library's side door"


def test_attach_indoor_rooms_between_two_doors_are_passages(graph: Graph) -> None:
    corridor = _edge(graph, "c", "m")  # c stands at k: a walk through a building
    assert corridor.passage and corridor.path_enu is None, corridor
    assert not _edge(graph, "m1", "m1a").passage, "one position: plain indoors"


def test_attach_indoor_door_link_outside_is_a_walk(graph: Graph) -> None:
    side = _edge(graph, "kd", "m")  # kd stands at k, 30 m north of m, in the open
    assert not side.passage, side
    assert side.length_m == pytest.approx(30.0), side.length_m
    assert side.kind is EdgeKind.ENTRANCE, side.kind
    assert _edge(graph, "k", "th").length_m == pytest.approx(60.0)


def test_attach_indoor_any_change_of_storey_is_stairs(graph: Graph) -> None:
    # The foyer (unknown floor) is halfway between 2, 0 (the door) and -1.
    assert _edge(graph, "f1", "te").kind is EdgeKind.STAIRS, "half a floor too"
    assert _edge(graph, "f2", "tm1").kind is EdgeKind.STAIRS
    assert _edge(graph, "f1", "f2").kind is EdgeKind.INDOOR, "one landing"


def test_step_free_conflicts_none_when_every_floor_change_is_stairs(
    graph: Graph,
) -> None:
    assert step_free_conflicts(graph) == [], step_free_conflicts(graph)


def test_step_free_conflicts_flag_a_floor_change_without_stairs(
    graph: Graph,
) -> None:
    flat = [
        e.model_copy(update={"kind": EdgeKind.INDOOR}) if e.id == "m|m1" else e
        for e in graph.edges
    ]
    conflicts = step_free_conflicts(graph.model_copy(update={"edges": flat}))
    assert len(conflicts) == 1 and "[-1, 0]" in conflicts[0], conflicts


def test_attach_indoor_far_floors_link_is_a_penalised_menu_jump() -> None:
    graph, report = build_graph(_posed(), _scenes(), BUILDING, "test", GraphParams())
    jump = _edge(graph, "lib", "t3")  # 3 to -1: four floors in one click
    assert jump.passage and jump.kind is EdgeKind.STAIRS, jump
    assert jump.cost_s == pytest.approx(
        INDOOR_LINK_M / WALKING_SPEED_MPS + 4 * STAIRS_S_PER_FLOOR
    ), "the stairs cost stays"
    assert report.indoor.menu_jumps == ["lib|t3"], report.indoor.menu_jumps
    assert not _edge(graph, "t2", "t3").passage, "one floor: a staircase"
    hub = _edge(graph, "m", "m5")  # the entrance hall to -5: stays as it is
    assert not hub.passage and hub.kind is EdgeKind.STAIRS, hub
