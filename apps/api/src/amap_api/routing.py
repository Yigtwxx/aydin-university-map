"""Shortest walking routes (A*) and turn-by-turn steps."""

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

import networkx as nx

from amap_api.graph_store import GraphStore
from amap_contracts.graph import WALKING_SPEED_MPS, EdgeKind, Node, NodeKind

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


@dataclass(frozen=True, slots=True)
class Step:
    node_id: str
    turn: Turn
    distance_m: float  # distance walked after this step's turn
    bearing_deg: float  # compass bearing of the walking direction


@dataclass(frozen=True, slots=True)
class Route:
    node_ids: list[str]
    length_m: float
    duration_s: float
    steps: list[Step]


_STAIRS = {EdgeKind.STAIRS.value}


# Walking past a door is fine, but routes should not hop between doorways to
# turn a corner: passing through an entrance that is neither end costs this.
ENTRANCE_PASS_S = 6.0
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
    """A* on walking time; the heuristic is straight-line time (admissible)."""
    for node_id in (source, target):
        if node_id not in store.nodes:
            raise KeyError(node_id)

    ends = {source, target}

    def weight(u: str, v: str, data: dict[str, object]) -> float | None:
        if avoid_stairs and data["kind"] in _STAIRS:
            return None  # hides the edge from the search
        cost = float(data["cost_s"])  # type: ignore[arg-type]
        for node_id in (u, v):
            if node_id not in ends and store.nodes[node_id].kind is NodeKind.ENTRANCE:
                cost += ENTRANCE_PASS_S / 2  # half per edge end: once per pass
        return cost

    def heuristic(u: str, v: str) -> float:
        return _distance(store.nodes[u], store.nodes[v]) / WALKING_SPEED_MPS

    try:
        path: list[str] = nx.astar_path(
            store.nx_graph, source, target, heuristic=heuristic, weight=weight
        )
    except nx.NetworkXNoPath as exc:
        raise NoRouteError(f"no route from {source} to {target}") from exc
    length = sum(
        float(store.nx_graph.edges[u, v]["length_m"]) for u, v in pairwise(path)
    )
    return Route(
        node_ids=path,
        length_m=length,
        duration_s=length / WALKING_SPEED_MPS,
        steps=build_steps(store, path),
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
