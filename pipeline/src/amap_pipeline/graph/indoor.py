"""Indoor routing from the tour's own links (no SfM indoors).

Indoor panoramas (and the entrances SfM could not pose) are reached from the
measured walking network through the tour's navigation links: entrance ->
corridor -> room. They become graph nodes without a measured position:

- **position**: the measured node they hang off (``Node.anchor``), inherited
  along the chain, so straight-line distances stay lower bounds of the walk
  (A*'s heuristic stays admissible). Clients draw them at that node;
- **building**: the block named by the label or area, else the block of the
  node they hang off;
- **floor**: named by the label or area (:mod:`amap_pipeline.tour.labels`;
  a hyphen's sign follows the linked spots of known floors); else carried
  over from linked spots that are on one known floor (a room off the
  "M Blok 2.Kat" corridor is on 2). A foyer linked to corridors of two
  floors is a staircase landing: it stays unknown, and so does anything only
  reachable through it. Entrances are at ground level (0) unless labelled;
- **edges**: the tour links between them, ``indoor`` (or ``entrance`` across a
  doorway), ``stairs`` wherever the storey changes (+15 s per floor), with an
  estimated length: 12 m, or the straight distance between the two positions
  when that is longer, so no edge is shorter than the line between its ends.
  Spots on unknown floors count as halfway between the known floors around
  them, so any change of floor through them is stairs too: a step-free route
  never hides a flight.

Links between two different positions are either a walk outside (two doors,
or a door and an open area: the outdoor rules apply, the line keeps clear of
buildings) or a **passage** through a building (``Edge.passage``), which the
map never draws and routes use only as a last resort. So is a link between
two rooms four or more floors apart (a menu jump in the tour: it keeps its
stairs cost). Footprint clearance does not apply to links within one
position: they are inside by definition.
"""

import math
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from amap_contracts.graph import (
    MENU_JUMP_FLOORS,
    WALKING_SPEED_MPS,
    Edge,
    EdgeKind,
    EdgeOrigin,
    LengthSource,
    LocalizedText,
    Node,
    NodeKind,
    PoseSource,
)
from amap_contracts.places import is_generic_area
from amap_pipeline.tour.labels import block_of, resolve_floors

XY = tuple[float, float]
# (a, b) -> the outdoor walking line between their positions, or None when
# no reasonable walk outside joins them (see graph.build.outdoor_line).
Walkable = Callable[[Node, Node], list[XY] | None]

# A tour link indoors: a corridor stretch or a door into a room.
INDOOR_LINK_M = 12.0
# Climbing or descending one storey by the stairs, on top of the walk.
STAIRS_S_PER_FLOOR = 15.0
ATTACHABLE_KINDS = frozenset({NodeKind.INDOOR.value, NodeKind.ENTRANCE.value})


@dataclass(slots=True)
class IndoorReport:
    nodes: int = 0
    entrances: int = 0  # unposed entrances reached through the tour
    edges: int = 0
    stairs: int = 0
    floors: dict[str, int] = field(
        default_factory=lambda: {"labelled": 0, "carried": 0, "unknown": 0}
    )
    buildings: dict[str, int] = field(
        default_factory=lambda: {"labelled": 0, "inherited": 0, "unknown": 0}
    )
    unreachable: list[str] = field(default_factory=list)  # indoor scenes left out
    passages: list[str] = field(default_factory=list)  # edges through buildings
    menu_jumps: list[str] = field(default_factory=list)  # far floors, one click
    door_walks: list[str] = field(default_factory=list)  # door links walked outside


def _text(scene: Mapping[str, Any], key: str) -> LocalizedText:
    return LocalizedText(tr=scene[key]["tr"], en=scene[key]["en"])


# Scene -> floor its label names (signs of hyphens resolved, see
# amap_pipeline.tour.labels.resolve_floors).
Floors = Mapping[str, int]


def _labelled_floor(
    name: str, scenes: Mapping[str, Mapping[str, Any]], floors: Floors
) -> int | None:
    floor = floors.get(name)
    if floor is None and scenes[name]["kind"] == NodeKind.ENTRANCE.value:
        return 0
    return floor


def _labelled_block(scene: Mapping[str, Any]) -> str | None:
    return block_of(scene["label"]["tr"], scene["area"]["tr"])


def with_entrance_floors(
    nodes: list[Node],
    scenes: Mapping[str, Mapping[str, Any]],
    floors: Floors | None = None,
) -> list[Node]:
    """Measured entrances get their floor: labelled, else ground level (0)."""
    floors = resolve_floors(scenes) if floors is None else floors
    return [
        n.model_copy(update={"floor": _labelled_floor(n.id, scenes, floors)})
        if n.kind is NodeKind.ENTRANCE and n.floor is None and n.id in scenes
        else n
        for n in nodes
    ]


def _hang_off(
    measured: Mapping[str, Node], scenes: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, str], dict[str, str | None]]:
    """Breadth-first through the tour from every measured node.

    Returns scene -> anchor and scene -> building. A scene reached from
    several spots at the same depth hangs off one in its own block (never one
    in another block, if it can help it), then one in its own tour area ("Tıp
    Fakültesi Hastanesi Giriş" off "Acil Giriş", not the library's door), then
    off an entrance, then the smallest id (deterministic).
    """
    anchor: dict[str, str] = {}
    building: dict[str, str | None] = {n.id: n.building for n in measured.values()}

    def attachable(name: str) -> bool:
        scene = scenes.get(name)
        return (
            scene is not None
            and name not in measured
            and name not in anchor
            and scene["kind"] in ATTACHABLE_KINDS
        )

    def anchor_of(name: str) -> Node:
        return measured[name] if name in measured else measured[anchor[name]]

    frontier = sorted(measured)
    while frontier:
        offers: dict[str, list[str]] = defaultdict(list)
        for parent in frontier:
            for name in scenes[parent]["links"]:
                if attachable(name):
                    offers[name].append(parent)
        for name in sorted(offers):
            own = _labelled_block(scenes[name])
            area = scenes[name]["area"]["tr"]

            def rank(
                parent: str, own: str | None = own, area: str = area
            ) -> tuple[bool, bool, bool, bool, str]:
                theirs = building[parent]
                known = own is not None and theirs is not None
                at = anchor_of(parent)
                same_area = not is_generic_area(area) and (
                    scenes[parent]["area"]["tr"] == area
                )
                return (
                    known and theirs != own,  # another block's spot
                    not (known and theirs == own),  # not visibly the same block
                    not same_area,
                    at.kind is not NodeKind.ENTRANCE,
                    parent,
                )

            parent = min(offers[name], key=rank)
            anchor[name] = anchor_of(parent).id
            building[name] = own or building[parent]
        frontier = sorted(offers)
    return anchor, {k: v for k, v in building.items() if k in anchor}


def _carried_floors(
    names: list[str], scenes: Mapping[str, Mapping[str, Any]], labelled: Floors
) -> dict[str, int]:
    """Floors of unlabelled indoor spots, carried over from linked spots.

    Spots sharing a label and area and linked to each other ("T Blok Fuaye"
    x4) are one place and decide together. A place takes a floor only when
    every linked place on a known floor (in a compatible block) is on that
    one floor; otherwise it is a landing between floors and stays unknown.
    """
    indoor = {n for n in names if scenes[n]["kind"] == NodeKind.INDOOR.value}
    key = {n: (scenes[n]["label"]["tr"], scenes[n]["area"]["tr"]) for n in indoor}

    # Union-find over same-place links.
    root = {n: n for n in indoor}

    def find(n: str) -> str:
        while root[n] != n:
            root[n] = root[root[n]]
            n = root[n]
        return n

    for n in sorted(indoor):
        for m in scenes[n]["links"]:
            if m in indoor and key[m] == key[n]:
                a, b = sorted((find(n), find(m)))
                root[b] = a
    unit = {n: find(n) for n in indoor}
    members: dict[str, list[str]] = defaultdict(list)
    for n in sorted(indoor):
        members[unit[n]].append(n)
    neighbours: dict[str, set[str]] = defaultdict(set)
    for n in indoor:
        for m in scenes[n]["links"]:
            if m in indoor and unit[m] != unit[n]:
                neighbours[unit[n]].add(unit[m])
    block = {u: _labelled_block(scenes[u]) for u in members}

    def compatible(u: str, v: str) -> bool:
        return block[u] is None or block[v] is None or block[u] == block[v]

    known: dict[str, int] = {}
    for u, group in members.items():
        floors = {
            f for n in group if (f := _labelled_floor(n, scenes, labelled)) is not None
        }
        if len(floors) == 1:
            known[u] = floors.pop()
    blocked: set[str] = set()
    frontier = sorted(known)
    while frontier:
        reached = sorted(
            {
                v
                for u in frontier
                for v in neighbours[u]
                if v not in known and v not in blocked and compatible(u, v)
            }
        )
        decided: dict[str, int] = {}
        for v in reached:
            floors = {
                known[w] for w in neighbours[v] if w in known and compatible(v, w)
            }
            if len(floors) == 1:
                decided[v] = floors.pop()
            else:
                blocked.add(v)
        known.update(decided)
        frontier = sorted(decided)
    return {n: known[unit[n]] for n in indoor if unit[n] in known}


def _routing_levels(
    nodes: Mapping[str, Node], scenes: Mapping[str, Mapping[str, Any]]
) -> dict[str, float]:
    """Storeys for edge costs and stairs, unknown floors included.

    Linked spots on unknown floors form a region; the whole region counts as
    halfway between the known floors around it. A landing between -1 and 4
    is at 1.5: walking -1 -> landing -> 4 pays for five flights, and both
    links are stairs. A region next to one known floor is on it. So every
    step-free stretch stays on one known floor. Only adds cost: routes stay
    optimal under the admissible heuristic.
    """
    known = {n.id: float(n.level) for n in nodes.values() if n.level is not None}
    unknown = sorted(n.id for n in nodes.values() if n.id not in known)
    root = {n: n for n in unknown}

    def find(n: str) -> str:
        while root[n] != n:
            root[n] = root[root[n]]
            n = root[n]
        return n

    for n in unknown:
        for m in scenes[n]["links"]:
            if m in root:
                a, b = sorted((find(n), find(m)))
                root[b] = a
    around: dict[str, set[float]] = defaultdict(set)
    for n in unknown:
        around[find(n)] |= {known[m] for m in scenes[n]["links"] if m in known}
    levels = dict(known)
    for n in unknown:
        seen = around[find(n)]
        if seen:
            levels[n] = (min(seen) + max(seen)) / 2
    return levels


def _menu_jump(a: Node, b: Node) -> bool:
    """Two spots of known floors MENU_JUMP_FLOORS or more apart, neither of them
    a door or open ground (an entrance hall links every floor's corridor)."""
    if NodeKind.ENTRANCE in (a.kind, b.kind) or NodeKind.OUTDOOR in (a.kind, b.kind):
        return False
    if a.floor is None or b.floor is None:
        return False
    return abs(a.floor - b.floor) >= MENU_JUMP_FLOORS


def position_of(node: Node) -> str:
    """The measured node a node stands at: its anchor, or itself."""
    return node.anchor or node.id


def _edge(
    a: Node,
    b: Node,
    yaw_ab: float | None,
    yaw_ba: float | None,
    levels: Mapping[str, float],
    walkable: Walkable | None,
) -> Edge:
    first, second = sorted((a, b), key=lambda n: n.id)
    yaw_first, yaw_second = (yaw_ab, yaw_ba) if first is a else (yaw_ba, yaw_ab)
    straight = math.dist(first.enu, second.enu)
    length = max(INDOOR_LINK_M, straight)
    path: list[XY] | None = None
    passage = False
    if position_of(first) != position_of(second):
        rooms = NodeKind.INDOOR in (first.kind, second.kind)
        line = None if rooms or walkable is None else walkable(first, second)
        if line is None:
            passage = True  # through a building: no line outside joins them
        else:
            dz = first.enu[2] - second.enu[2]
            walked = sum(math.dist(p, q) for p, q in pairwise(line))
            length = max(INDOOR_LINK_M, math.hypot(walked, dz))
            if len(line) > 2:
                path = [(round(x, 2), round(y, 2)) for x, y in line]
    low, high = levels.get(first.id), levels.get(second.id)
    climb = abs(low - high) if low is not None and high is not None else 0.0
    if _menu_jump(first, second):
        passage = True  # a click in the tour menu, not a flight of stairs
    if climb > 0:  # any change of storey, half a landing included
        kind = EdgeKind.STAIRS
    elif first.kind is NodeKind.INDOOR and second.kind is NodeKind.INDOOR:
        kind = EdgeKind.INDOOR
    else:
        kind = EdgeKind.ENTRANCE  # through a doorway
    return Edge(
        id=f"{first.id}|{second.id}",
        source=first.id,
        target=second.id,
        kind=kind,
        origin=EdgeOrigin.TOUR,
        length_m=length,
        cost_s=length / WALKING_SPEED_MPS + STAIRS_S_PER_FLOOR * climb,
        length_source=LengthSource.ESTIMATE,
        path_enu=path,
        source_yaw_deg=yaw_first,
        target_yaw_deg=yaw_second,
        passage=passage,
    )


def attach_indoor(
    measured: list[Node],
    scenes: Mapping[str, Mapping[str, Any]],
    walkable: Walkable | None = None,
) -> tuple[list[Node], list[Edge], IndoorReport]:
    """Measured nodes (entrance floors set) + indoor nodes, and their edges.

    ``walkable`` decides whether two doors at different positions are a walk
    outside; without it every such link is a passage.
    """
    report = IndoorReport()
    labelled = resolve_floors(scenes)
    measured = with_entrance_floors(measured, scenes, labelled)
    by_id = {n.id: n for n in measured}
    anchor, building = _hang_off(by_id, scenes)
    names = sorted(anchor)
    carried = _carried_floors(names, scenes, labelled)

    attached: list[Node] = []
    for name in names:
        scene = scenes[name]
        at = by_id[anchor[name]]
        floor = _labelled_floor(name, scenes, labelled)
        if floor is not None:
            report.floors["labelled"] += 1
        elif name in carried:
            floor = carried[name]
            report.floors["carried"] += 1
        else:
            report.floors["unknown"] += 1
        if _labelled_block(scene) is not None:
            report.buildings["labelled"] += 1
        elif building[name] is not None:
            report.buildings["inherited"] += 1
        else:
            report.buildings["unknown"] += 1
        kind = NodeKind(scene["kind"])
        report.entrances += kind is NodeKind.ENTRANCE
        attached.append(
            Node(
                id=name,
                kind=kind,
                lat=at.lat,
                lng=at.lng,
                alt_m=at.alt_m,
                enu=at.enu,
                heading_deg=0.0,  # unknown: no measured orientation indoors
                pose_source=PoseSource.INTERPOLATED,
                label=_text(scene, "label"),
                area=_text(scene, "area"),
                building=building[name],
                floor=floor,
                anchor=at.id,
            )
        )
    report.nodes = len(attached)

    everything = {**by_id, **{n.id: n for n in attached}}
    levels = _routing_levels(everything, scenes)
    edges: dict[str, Edge] = {}
    for name in names:
        yaws = scenes[name].get("link_yaw", {})
        for other in scenes[name]["links"]:
            if other not in everything:
                continue
            key = "|".join(sorted((name, other)))
            if key in edges:
                continue
            back = scenes[other].get("link_yaw", {}).get(name)
            edges[key] = _edge(
                everything[name],
                everything[other],
                yaws.get(other),
                back,
                levels,
                walkable,
            )
    report.edges = len(edges)
    report.stairs = sum(e.kind is EdgeKind.STAIRS for e in edges.values())
    report.passages = sorted(k for k, e in edges.items() if e.passage)
    report.menu_jumps = sorted(
        k
        for k, e in edges.items()
        if _menu_jump(everything[e.source], everything[e.target])
    )
    report.door_walks = sorted(
        k
        for k, e in edges.items()
        if not e.passage
        and position_of(everything[e.source]) != position_of(everything[e.target])
    )
    report.unreachable = sorted(
        s
        for s, scene in scenes.items()
        if scene["kind"] == NodeKind.INDOOR.value and s not in everything
    )
    return [*measured, *attached], sorted(edges.values(), key=lambda e: e.id), report
