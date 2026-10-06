"""Shortest walking routes (A*) and turn-by-turn steps."""

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

import networkx as nx

from amap_api.graph_store import GraphStore
from amap_contracts.graph import WALKING_SPEED_MPS, EdgeKind, Node


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


def _distance(a: Node, b: Node) -> float:
    return math.dist(a.enu, b.enu)


def shortest_route(
    store: GraphStore, source: str, target: str, avoid_stairs: bool = False
) -> Route:
    """A* on walking time; the heuristic is straight-line time (admissible)."""
    for node_id in (source, target):
        if node_id not in store.nodes:
            raise KeyError(node_id)

    def weight(_u: str, _v: str, data: dict[str, object]) -> float | None:
        if avoid_stairs and data["kind"] in _STAIRS:
            return None  # hides the edge from the search
        return float(data["cost_s"])  # type: ignore[arg-type]

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
    dx, dy = b.enu[0] - a.enu[0], b.enu[1] - a.enu[1]
    return math.degrees(math.atan2(dx, dy)) % 360.0


def classify_turn(delta_deg: float) -> Turn:
    """``delta_deg`` = new bearing - old bearing, wrapped to (-180, 180]."""
    magnitude = abs(delta_deg)
    if magnitude <= 20:
        return Turn.STRAIGHT
    if magnitude > 150:
        return Turn.U_TURN
    right = delta_deg > 0
    if magnitude <= 60:
        return Turn.SLIGHT_RIGHT if right else Turn.SLIGHT_LEFT
    if magnitude <= 120:
        return Turn.RIGHT if right else Turn.LEFT
    return Turn.SHARP_RIGHT if right else Turn.SHARP_LEFT


def build_steps(store: GraphStore, path: list[str]) -> list[Step]:
    """One step per direction change; consecutive straight segments are merged."""
    nodes = [store.nodes[n] for n in path]
    if len(nodes) == 1:
        return [Step(path[0], Turn.ARRIVE, 0.0, nodes[0].heading_deg)]
    steps: list[Step] = []
    prev_bearing: float | None = None
    for a, b in pairwise(nodes):
        bearing = bearing_deg(a, b)
        length = _distance(a, b)
        if prev_bearing is None:
            steps.append(Step(a.id, Turn.START, length, bearing))
        else:
            turn = classify_turn((bearing - prev_bearing + 180.0) % 360.0 - 180.0)
            if turn is Turn.STRAIGHT:
                last = steps[-1]
                steps[-1] = Step(
                    last.node_id, last.turn, last.distance_m + length, last.bearing_deg
                )
            else:
                steps.append(Step(a.id, turn, length, bearing))
        prev_bearing = bearing
    steps.append(Step(nodes[-1].id, Turn.ARRIVE, 0.0, prev_bearing or 0.0))
    return steps
