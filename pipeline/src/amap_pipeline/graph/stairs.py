"""Outdoor flights of steps in the walking graph.

A walking edge climbs a flight when its line crosses the flight's footprint and
its two ends lie on either side of the flight's middle (one below, one
above). Such an edge becomes a stairs edge, so "avoid stairs" routes go round
it, by a ramp where there is one.
"""

from collections.abc import Sequence

from shapely.geometry import LineString, Polygon

from amap_contracts.furniture import Stairs
from amap_contracts.graph import EdgeKind, Graph

_WALKED = {EdgeKind.OUTDOOR, EdgeKind.ENTRANCE}


def footprint(flight: Stairs) -> Polygon:
    line = LineString([flight.foot, flight.top])
    return line.buffer(flight.width_m / 2.0, cap_style="flat")


def _along(flight: Stairs, x: float, y: float) -> float:
    """Position along the flight axis: 0 at the foot, 1 at the top."""
    fx, fy = flight.foot
    dx, dy = flight.top[0] - fx, flight.top[1] - fy
    return ((x - fx) * dx + (y - fy) * dy) / (dx * dx + dy * dy)


def climbs(flight: Stairs, path: Sequence[tuple[float, float]]) -> bool:
    if len(path) < 2:
        return False
    if not LineString(path).intersects(footprint(flight)):
        return False
    a = _along(flight, *path[0])
    b = _along(flight, *path[-1])
    return (a - 0.5) * (b - 0.5) < 0


def mark_outdoor_stairs(
    graph: Graph, flights: Sequence[Stairs]
) -> tuple[Graph, list[str]]:
    """Graph with walking edges over a flight turned into stairs edges."""
    if not flights:
        return graph, []
    xy = {n.id: (n.enu[0], n.enu[1]) for n in graph.nodes}
    changed: list[str] = []
    edges = []
    for edge in graph.edges:
        path = (
            [(x, y) for x, y in edge.path_enu]
            if edge.path_enu
            else [xy[edge.source], xy[edge.target]]
        )
        if edge.kind in _WALKED and any(climbs(f, path) for f in flights):
            edges.append(edge.model_copy(update={"kind": EdgeKind.STAIRS}))
            changed.append(edge.id)
        else:
            edges.append(edge)
    return graph.model_copy(update={"edges": edges}), changed
