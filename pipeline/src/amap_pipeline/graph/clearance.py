"""Keep the walking graph out of buildings.

SfM camera positions and OSM footprints disagree by a metre or two, and a tour
link between two panoramas is a straight line that can cut a building corner,
or (from an entrance to the far side of a block) run straight through it.
Neither may reach the map: a route through a wall is simply wrong.

- :func:`snap_nodes` moves nodes that sit inside (or hug) a footprint to just
  outside its nearest wall; an entrance lands in front of its door.
- :func:`walk_around` replaces a blocked straight edge with the shortest line
  around the buildings (a visibility graph over their clearance-grown
  corners), or reports that there is no reasonable detour.
"""

import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

XY = tuple[float, float]

# Lines may graze a wall by this much (OSM footprints are drawn at the outer
# face of walls, plaster and all).
GRAZE_M = 0.3
# Detours keep this far from walls; snapped nodes stand this far out.
CLEARANCE_M = 1.2
# How far a detour may search around the straight line.
SEARCH_M = 45.0


@dataclass(frozen=True, slots=True)
class Obstacles:
    """Building footprints, grown and shrunk for the two kinds of test."""

    union: BaseGeometry  # footprints as mapped
    blocked: BaseGeometry  # footprints shrunk by GRAZE_M: lines must not touch
    grown: BaseGeometry  # footprints grown by CLEARANCE_M: detour corners

    @classmethod
    def of(cls, footprints: BaseGeometry | Sequence[Polygon]) -> "Obstacles":
        union = (
            footprints
            if isinstance(footprints, BaseGeometry)
            else unary_union(list(footprints))
        )
        blocked = union.buffer(-GRAZE_M, join_style="mitre")
        grown = union.buffer(CLEARANCE_M, join_style="mitre", mitre_limit=2.0)
        for geometry in (union, blocked, grown):
            shapely.prepare(geometry)
        return cls(union=union, blocked=blocked, grown=grown)

    def crosses(self, a: XY, b: XY) -> bool:
        return bool(self.blocked.intersects(LineString([a, b])))


def snap_point(p: XY, obstacles: Obstacles, margin_m: float = CLEARANCE_M) -> XY:
    """``p`` if clear of every building, else just outside the nearest wall."""
    point = Point(p)
    if obstacles.union.distance(
        point
    ) >= margin_m * 0.5 and not obstacles.union.contains(point):
        return p
    # The nearest point on the clearance-grown outline is outside and clear.
    boundary = obstacles.grown.boundary
    target = nearest_points(boundary, point)[0]
    # Nudge a hair further out so the result is not on the boundary itself.
    dx, dy = target.x - p[0], target.y - p[1]
    length = math.hypot(dx, dy) or 1.0
    return (target.x + dx / length * 0.05, target.y + dy / length * 0.05)


def _corners(geometry: BaseGeometry, near: BaseGeometry) -> list[XY]:
    """Convex-ish outline vertices of ``geometry`` within the search area."""
    points: list[XY] = []
    polygons = getattr(geometry, "geoms", [geometry])
    for polygon in polygons:
        if not isinstance(polygon, Polygon) or not polygon.intersects(near):
            continue
        simple = polygon.simplify(0.4)
        if not isinstance(simple, Polygon):
            continue
        ring = simple.exterior
        points.extend((float(x), float(y)) for x, y in list(ring.coords)[:-1])
    return points


def walk_around(a: XY, b: XY, obstacles: Obstacles) -> list[XY] | None:
    """Shortest polyline from ``a`` to ``b`` that stays out of buildings.

    Returns ``[a, b]`` when the straight line is clear and ``None`` when no
    path exists within the search area.
    """
    if not obstacles.crosses(a, b):
        return [a, b]
    area = LineString([a, b]).buffer(SEARCH_M)
    grown = obstacles.grown.intersection(area)
    vertices = [a, b] + [
        c
        for c in _corners(grown, area)
        if not obstacles.blocked.contains(Point(c)) and area.contains(Point(c))
    ]
    # Corners of the grown outline are clear of buildings by construction;
    # a segment is usable when it does not cut a (shrunk) footprint.
    count = len(vertices)
    best = [math.inf] * count
    previous = [-1] * count
    best[0] = 0.0
    heap = [(0.0, 0)]
    clear: dict[tuple[int, int], bool] = {}

    def visible(i: int, j: int) -> bool:
        key = (min(i, j), max(i, j))
        if key not in clear:
            clear[key] = not obstacles.crosses(vertices[i], vertices[j])
        return clear[key]

    while heap:
        cost, i = heapq.heappop(heap)
        if i == 1:
            break
        if cost > best[i]:
            continue
        for j in range(count):
            if j == i:
                continue
            step = math.dist(vertices[i], vertices[j])
            if cost + step >= best[j] or not visible(i, j):
                continue
            best[j] = cost + step
            previous[j] = i
            heapq.heappush(heap, (best[j], j))
    if math.isinf(best[1]):
        return None
    path = [1]
    while path[-1] != 0:
        path.append(previous[path[-1]])
    return [vertices[k] for k in reversed(path)]


def path_length(path: Sequence[XY]) -> float:
    return sum(math.dist(p, q) for p, q in pairwise(path))
