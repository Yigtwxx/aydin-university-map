"""Shortest walking routes (A*) and turn-by-turn steps.

Outdoors, steps follow the walking line's real turns (compass bearings).
Indoor spots have no measured position (they stand at the entrance they hang
off), so inside buildings the steps say what to do instead: enter the
block, continue to a room, take the stairs up or down, walk through a
building, leave it, arrive; their distances are estimates.
"""

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

import networkx as nx

from amap_api.graph_store import GraphStore
from amap_contracts.graph import (
    MENU_JUMP_FLOORS,
    WALKING_SPEED_MPS,
    EdgeKind,
    LengthSource,
    LocalizedText,
    Node,
    NodeKind,
)
from amap_contracts.places import is_generic_area

XY = tuple[float, float]


class NoRouteError(LookupError):
    """No walkable path between the two nodes (with the given restrictions)."""


class Turn(StrEnum):
    START = "start"
    STRAIGHT = "straight"
    SLIGHT_LEFT = "slight_left"
    LEFT = "left"
    SHARP_LEFT = "sharp_left"
    SLIGHT_RIGHT = "slight_right"
    RIGHT = "right"
    SHARP_RIGHT = "sharp_right"
    U_TURN = "u_turn"
    ARRIVE = "arrive"
    # Inside buildings (and at their doors):
    ENTER = "enter"
    EXIT = "exit"  # leave the building, then head along bearing_deg
    GO_TO = "go_to"  # continue to the spot named by `place`
    STAIRS_UP = "stairs_up"
    STAIRS_DOWN = "stairs_down"
    THROUGH = "through"  # walk through a building (a passage), out the far door


@dataclass(frozen=True, slots=True)
class Step:
    node_id: str
    turn: Turn
    distance_m: float  # distance walked after this step's turn
    bearing_deg: float  # compass bearing of the walking direction (0 indoors)
    # Inside a building: no compass, estimated distance.
    indoor: bool = False
    building: str | None = None  # block code ("M") the step is in, enters or leaves
    floor: int | None = None  # storey at the step's spot (after its stairs)
    floors: int = 0  # storeys climbed (+) or descended (-) by a stairs step
    place: LocalizedText | None = None  # the spot walked to (or started at)


@dataclass(frozen=True, slots=True)
class Route:
    node_ids: list[str]
    length_m: float
    duration_s: float
    steps: list[Step]
    approximate: bool = False  # includes estimated (indoor) lengths


_STAIRS = {EdgeKind.STAIRS.value}


# Walking past a door is fine, but routes should not hop between doorways to
# turn a corner: passing through an entrance that is neither end costs this.
ENTRANCE_PASS_S = 6.0
# A passage through a building the route neither starts nor ends in costs
# this on top of its walk: outdoor routes cut through only as a last resort
# (a flat minute, so a short passage never beats a sensible walk outside).
PASSAGE_S = 60.0
# A line through café seating or a hedge, or over a wall or fence with no
# flight or gate noted, is only taken when a clean walk costs more than this.
CROSSING_S = {"soft": 10.0, "barrier": 30.0}
# A spot taken among café tables or planting: walking through it (neither
# end of the route) crosses them as much as such a line does.
AMID_PASS_S = CROSSING_S["soft"]
# Turns are read off the walking line after smoothing away this much wobble.
LINE_TOLERANCE_M = 1.5
# Bends up to this many degrees read as walking straight on.
STRAIGHT_DEG = 35.0
# Shorter steps between two others are folded into the step before them.
MIN_STEP_M = 8.0


def _distance(a: Node, b: Node) -> float:
    return math.dist(a.enu, b.enu)


def shortest_route(
    store: GraphStore, source: str, target: str, avoid_stairs: bool = False
) -> Route:
    """A* on walking time; the heuristic is straight-line time (admissible).

    Indoor spots stand at the entrance they hang off and no indoor edge is
    shorter than the line between its ends, so the heuristic stays admissible
    indoors too; the surcharges below only ever add cost. A passage is free
    inside the indoor network of a room the route starts or ends in (its own
    building's corridors); everywhere else, and always for a menu jump
    between far floors, it costs ``PASSAGE_S`` extra.
    """
    for node_id in (source, target):
        if node_id not in store.nodes:
            raise KeyError(node_id)

    ends = {source, target}
    # The indoor networks of a room at either end: passages there are its
    # own building's corridors. A door is outside: no building is "home".
    home = {
        store.indoor_cluster.get(n)
        for n in ends
        if store.nodes[n].kind is NodeKind.INDOOR
    } - {None}

    def weight(u: str, v: str, data: dict[str, object]) -> float | None:
        if avoid_stairs and (
            data["kind"] in _STAIRS or data.get("crosses") == "barrier"
        ):
            # Hides the edge from the search; a line over a wall or a level
            # change with no flight or ramp noted is no step-free walk either.
            return None
        cost = float(data["cost_s"])  # type: ignore[arg-type]
        for node_id in (u, v):
            if node_id in ends:
                continue
            node = store.nodes[node_id]
            if node.kind is NodeKind.ENTRANCE:
                cost += ENTRANCE_PASS_S / 2  # half per edge end: once per pass
            if node.amid_obstacles:
                cost += AMID_PASS_S / 2
        if data.get("passage") and (
            _menu_jump(store, u, v)
            or not (
                store.indoor_cluster.get(u) in home
                or store.indoor_cluster.get(v) in home
            )
        ):
            cost += PASSAGE_S
        crosses = data.get("crosses")
        if isinstance(crosses, str):
            cost += CROSSING_S.get(crosses, 0.0)
        return cost

    def heuristic(u: str, v: str) -> float:
        return _distance(store.nodes[u], store.nodes[v]) / WALKING_SPEED_MPS

    try:
        path: list[str] = nx.astar_path(
            store.nx_graph, source, target, heuristic=heuristic, weight=weight
        )
    except nx.NetworkXNoPath as exc:
        raise NoRouteError(f"no route from {source} to {target}") from exc
    edges = [store.nx_graph.edges[u, v] for u, v in pairwise(path)]
    length = sum(float(e["length_m"]) for e in edges)
    # Walking time plus the stairs (an outdoor edge costs its length at pace).
    duration = math.fsum(float(e["cost_s"]) for e in edges)
    return Route(
        node_ids=path,
        length_m=length,
        duration_s=duration,
        steps=build_steps(store, path),
        approximate=any(
            e.get("length_source") == LengthSource.ESTIMATE.value for e in edges
        ),
    )


def bearing_deg(a: Node, b: Node) -> float:
    """Compass bearing from a to b (local ENU: x east, y north)."""
    return _bearing((a.enu[0], a.enu[1]), (b.enu[0], b.enu[1]))


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    return math.degrees(math.atan2(dx, dy)) % 360.0


def walking_line(store: GraphStore, a: Node, b: Node) -> list[tuple[float, float]]:
    """The edge's walking line from a to b (bent around buildings if needed)."""
    data = store.nx_graph.edges[a.id, b.id]
    path = data.get("path_enu")
    if not path:
        return [(a.enu[0], a.enu[1]), (b.enu[0], b.enu[1])]
    line = [(float(x), float(y)) for x, y in path]
    return line if data.get("source") == a.id else line[::-1]


def classify_turn(delta_deg: float) -> Turn:
    """``delta_deg`` = new bearing - old bearing, wrapped to (-180, 180]."""
    magnitude = abs(delta_deg)
    # Panorama positions wobble by a metre or two; small bends are "straight".
    if magnitude <= STRAIGHT_DEG:
        return Turn.STRAIGHT
    if magnitude > 150:
        return Turn.U_TURN
    right = delta_deg > 0
    if magnitude <= 60:
        return Turn.SLIGHT_RIGHT if right else Turn.SLIGHT_LEFT
    if magnitude <= 120:
        return Turn.RIGHT if right else Turn.LEFT
    return Turn.SHARP_RIGHT if right else Turn.SHARP_LEFT


def _simplify(points: list[XY], tolerance: float) -> list[int]:
    """Douglas-Peucker; returns the indices of the vertices kept."""
    if len(points) < 3:
        return list(range(len(points)))
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        (ax, ay), (bx, by) = points[start], points[end]
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        worst, index = -1.0, -1
        for i in range(start + 1, end):
            px, py = points[i]
            t = 0.0 if length2 == 0 else ((px - ax) * dx + (py - ay) * dy) / length2
            t = min(1.0, max(0.0, t))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > worst:
                worst, index = d, i
        if worst > tolerance:
            keep.add(index)
            stack.extend([(start, index), (index, end)])
    return sorted(keep)


def build_steps(store: GraphStore, path: list[str]) -> list[Step]:
    """Turn-by-turn steps; indoor stretches get indoor steps (see module doc)."""
    if len(path) > 1 and (
        any(store.nodes[n].approximate for n in path)
        or any(_passage(store, a, b) for a, b in pairwise(path))
    ):
        return _mixed_steps(store, path)
    return _walk_steps(store, path)


def drawable_parts(store: GraphStore, path: list[str]) -> list[list[str]]:
    """The runs of a route the map can draw: measured nodes joined by walks.

    The line breaks at indoor spots (borrowed positions) and at passages
    through buildings; runs of one node are nothing to draw.
    """
    parts: list[list[str]] = [[]]
    for i, node_id in enumerate(path):
        drawable = not store.nodes[node_id].approximate
        joined = i > 0 and not _passage(store, path[i - 1], node_id)
        if not drawable or not joined:
            parts.append([])
        if drawable:
            parts[-1].append(node_id)
    return [part for part in parts if len(part) > 1]


def _walk_steps(store: GraphStore, path: list[str]) -> list[Step]:
    """Steps at the real turns of the walking line, straight runs merged.

    The line follows every edge (round building corners too) and is smoothed
    of panorama-position wobble first, so a jog of a metre is not a turn.
    Each step is pinned to the route node nearest its turn (for the 360°
    preview).
    """
    nodes = [store.nodes[n] for n in path]
    if len(nodes) == 1:
        return [Step(path[0], Turn.ARRIVE, 0.0, nodes[0].heading_deg)]
    line: list[XY] = [(nodes[0].enu[0], nodes[0].enu[1])]
    node_at = [0.0]  # distance along the line of each route node
    along = [0.0]  # distance along the line of each vertex
    for a, b in pairwise(nodes):
        for point in walking_line(store, a, b)[1:]:
            along.append(along[-1] + math.dist(line[-1], point))
            line.append(point)
        node_at.append(along[-1])
    total = along[-1]
    route_length = sum(
        float(store.nx_graph.edges[a.id, b.id]["length_m"]) for a, b in pairwise(nodes)
    )
    # Report distances in the route's own (3D, edge-length) metres.
    scale = route_length / total if total > 0 else 1.0

    kept = [i for i in _simplify(line, LINE_TOLERANCE_M)]
    if len(kept) < 2 or total == 0:
        bearing = bearing_deg(nodes[0], nodes[-1])
        return [
            Step(path[0], Turn.START, route_length, bearing),
            Step(path[-1], Turn.ARRIVE, 0.0, bearing),
        ]
    bearings = [_bearing(line[i], line[j]) for i, j in pairwise(kept)]

    def nearest_node(distance: float) -> str:
        best = min(range(len(path)), key=lambda k: abs(node_at[k] - distance))
        return path[best]

    # Turn points: (distance along, turn, outgoing bearing).
    marks: list[tuple[float, Turn, float]] = [(0.0, Turn.START, bearings[0])]
    for k in range(1, len(bearings)):
        delta = (bearings[k] - bearings[k - 1] + 180.0) % 360.0 - 180.0
        turn = classify_turn(delta)
        if turn is not Turn.STRAIGHT:
            marks.append((along[kept[k]], turn, bearings[k]))
    steps: list[Step] = []
    for (at, turn, bearing), following in zip(
        marks, [*(m[0] for m in marks[1:]), total], strict=True
    ):
        node_id = path[0] if turn is Turn.START else nearest_node(at)
        steps.append(Step(node_id, turn, (following - at) * scale, bearing))
    steps.append(Step(path[-1], Turn.ARRIVE, 0.0, bearings[-1]))
    return _fold_short_steps(steps)


def _fold_short_steps(steps: list[Step]) -> list[Step]:
    """Merge a jog of a few metres into the step before it."""
    folded: list[Step] = []
    for step in steps:
        short = step.distance_m < MIN_STEP_M
        if folded and short and step.turn not in (Turn.START, Turn.ARRIVE):
            last = folded[-1]
            folded[-1] = Step(
                last.node_id,
                last.turn,
                last.distance_m + step.distance_m,
                last.bearing_deg,
            )
            continue
        folded.append(step)
    return folded


# --- Indoor stretches -------------------------------------------------------


def _menu_jump(store: GraphStore, a: str, b: str) -> bool:
    """Rooms MENU_JUMP_FLOORS or more storeys apart: a click in the tour menu,
    penalised even inside the route's own building (doors excluded, as in the
    pipeline: an entrance hall links every floor)."""
    first, second = store.nodes[a], store.nodes[b]
    if first.kind is not NodeKind.INDOOR or second.kind is not NodeKind.INDOOR:
        return False
    low, high = first.floor, second.floor
    return low is not None and high is not None and abs(low - high) >= MENU_JUMP_FLOORS


def _passage(store: GraphStore, a: str, b: str) -> bool:
    return bool(store.nx_graph.edges[a, b].get("passage"))


def _legs(store: GraphStore, path: list[str]) -> list[tuple[bool, int, int]]:
    """(inside, first, last node index): runs of outdoor or indoor edges.

    An edge is indoor when either end is an indoor (approximate) spot or it
    is a passage, so a measured entrance hall passed between two floors
    stays inside.
    """
    legs: list[tuple[bool, int, int]] = []
    for i, (a, b) in enumerate(pairwise(path)):
        inside = (
            store.nodes[a].approximate
            or store.nodes[b].approximate
            or _passage(store, a, b)
        )
        if legs and legs[-1][0] == inside:
            legs[-1] = (inside, legs[-1][1], i + 1)
        else:
            legs.append((inside, i, i + 1))
    return legs


def _building(nodes: list[Node]) -> str | None:
    """Block code of the first indoor spot that names one."""
    return next(
        (n.building for n in nodes if n.kind is NodeKind.INDOOR and n.building),
        next((n.building for n in nodes if n.building), None),
    )


def _through_building(nodes: list[Node]) -> str | None:
    """The block a passage between doors runs through: its indoor side."""
    return _building([n for n in nodes if n.approximate]) or _building(nodes)


def _building_name(nodes: list[Node]) -> LocalizedText | None:
    """The tour area of the first indoor spot ("Kütüphane"), else of the first
    door known only from the tour, for blocks without a code; None when it is
    the campus at large."""
    named = [n for n in nodes if not is_generic_area(n.area.tr)]
    return next(
        (n.area for n in named if n.kind is NodeKind.INDOOR),
        next((n.area for n in named if n.approximate), None),
    )


def _indoor_leg(
    store: GraphStore, path: list[str], first: int, last: int, arrive: bool
) -> list[tuple[int, Step]]:
    """Steps of one indoor leg, keyed by the path index they are pinned to.

    ``first`` is either the route's start or the measured node the leg leaves
    the walking network at (a door). Distances are filled in later.
    """
    nodes = [store.nodes[n] for n in path]
    leg = nodes[first : last + 1]
    rooms = any(n.kind is NodeKind.INDOOR for n in leg)
    passages = [i for i in range(first, last) if _passage(store, path[i], path[i + 1])]
    building = _building(leg)
    out: list[tuple[int, Step]] = []
    start = nodes[first]
    pin = first
    if first == 0 and start.approximate:
        out.append(
            (
                0,
                Step(
                    start.id,
                    Turn.START,
                    0.0,
                    0.0,
                    indoor=True,
                    building=start.building,
                    floor=start.floor,
                    place=start.label,
                ),
            )
        )
    elif rooms:
        # Through the door: the entrance spots just behind it are part of it.
        while pin + 1 < last and nodes[pin + 1].kind is NodeKind.ENTRANCE:
            pin += 1
        door = nodes[pin]
        out.append(
            (
                pin,
                Step(
                    door.id,
                    Turn.ENTER,
                    0.0,
                    0.0,
                    indoor=True,
                    building=building,
                    floor=door.level,
                    place=None if building else _building_name(leg),
                ),
            )
        )
    if passages and not rooms:
        # Between two doors through a building: one step for the whole walk.
        at = passages[0]
        building = _through_building(leg)
        out.append(
            (
                at,
                Step(
                    nodes[at].id,
                    Turn.THROUGH,
                    0.0,
                    0.0,
                    indoor=True,
                    building=building,
                    place=None if building else _building_name(leg),
                ),
            )
        )
        if arrive:
            end = nodes[last]
            out.append(
                (last, Step(end.id, Turn.ARRIVE, 0.0, 0.0, building=end.building))
            )
        return out
    level = nodes[pin].level
    label = nodes[pin].label.tr
    for i in range(pin + 1, last + 1):
        node = nodes[i]
        here = node.level
        if here is not None and level is not None and here != level:
            climbed = here - level
            previous = out[-1][1] if out else None
            if (
                previous is not None
                and previous.turn in (Turn.STAIRS_UP, Turn.STAIRS_DOWN)
                and (previous.floors > 0) == (climbed > 0)
            ):
                # Nothing to say in between: one climb, not two.
                climbed += previous.floors
                out.pop()
            turn = Turn.STAIRS_UP if climbed > 0 else Turn.STAIRS_DOWN
            out.append(
                (
                    i,
                    Step(
                        node.id,
                        turn,
                        0.0,
                        0.0,
                        indoor=True,
                        building=node.building or building,
                        floor=here,
                        floors=climbed,
                        place=node.label,
                    ),
                )
            )
            label = node.label.tr
        if here is not None:
            level = here
        if i == last:
            if arrive:
                out.append(
                    (
                        i,
                        Step(
                            node.id,
                            Turn.ARRIVE,
                            0.0,
                            0.0,
                            indoor=rooms,  # a door known from the tour is outside
                            building=node.building or building,
                            floor=node.floor,
                            place=node.label,
                        ),
                    )
                )
            break  # leaving: the walk outside takes over
        # The destination's own panoramas need no "continue to" of their own.
        into_destination = arrive and all(
            n.label.tr == node.label.tr for n in nodes[i : last + 1]
        )
        if (
            node.label.tr != label
            and not (out and out[-1][0] == i)
            and not into_destination
        ):
            out.append(
                (
                    i,
                    Step(
                        node.id,
                        Turn.GO_TO,
                        0.0,
                        0.0,
                        # Among doors (no rooms in the leg) the walker is outside.
                        indoor=rooms,
                        building=node.building or building,
                        floor=node.floor,
                        place=node.label,
                    ),
                )
            )
            label = node.label.tr
    return out


def _mixed_steps(store: GraphStore, path: list[str]) -> list[Step]:
    """Outdoor legs as walking steps, indoor legs as indoor steps."""
    nodes = [store.nodes[n] for n in path]
    along = [0.0]
    for a, b in pairwise(path):
        along.append(along[-1] + float(store.nx_graph.edges[a, b]["length_m"]))
    # (path index of the step's spot, index its distance counts from or None
    # for walking steps, which measured their own, step)
    pinned: list[tuple[int, int | None, Step]] = []
    legs = _legs(store, path)
    bearing: float | None = None  # the last walking direction outside
    for k, (inside, first, last) in enumerate(legs):
        final = k == len(legs) - 1
        if inside:
            leg = _indoor_leg(store, path, first, last, arrive=final)
            # The walk from the door to the first indoor step belongs to it.
            pinned += [(i, first if j == 0 else i, st) for j, (i, st) in enumerate(leg)]
            continue
        walk = _walk_steps(store, path[first : last + 1])
        arrival = walk[-1].bearing_deg
        if not final:
            walk = walk[:-1]  # its arrival is the next leg's start
        left = legs[k - 1] if k > 0 else None
        for j, step in enumerate(walk):
            index = path.index(step.node_id, first, last + 1)
            if j == 0 and left is not None:
                leg = nodes[left[1] : left[2] + 1]
                inside = any(n.kind is NodeKind.INDOOR for n in leg) or any(
                    _passage(store, path[i], path[i + 1])
                    for i in range(left[1], left[2])
                )
                if inside:
                    # Out of the building and on along the first bearing.
                    rooms = any(n.kind is NodeKind.INDOOR for n in leg)
                    block = _building(leg[::-1]) if rooms else _through_building(leg)
                    step = Step(
                        step.node_id,
                        Turn.EXIT,
                        step.distance_m,
                        step.bearing_deg,
                        building=block,
                        place=None if block else _building_name(leg[::-1]),
                    )
                elif bearing is not None:
                    # Past a door outside: a turn from the way the walk came.
                    delta = (step.bearing_deg - bearing + 180.0) % 360.0 - 180.0
                    step = Step(
                        step.node_id,
                        classify_turn(delta),
                        step.distance_m,
                        step.bearing_deg,
                    )
            pinned.append((index, None, step))
        bearing = arrival
    steps: list[Step] = []
    for n, (index, since, step) in enumerate(pinned):
        if since is not None:
            following = pinned[n + 1][0] if n + 1 < len(pinned) else index
            step = Step(
                step.node_id,
                step.turn,
                max(0.0, along[following] - along[since]),
                step.bearing_deg,
                indoor=step.indoor,
                building=step.building,
                floor=step.floor,
                floors=step.floors,
                place=step.place,
            )
        steps.append(step)
    return steps
