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

Buildings are not the only things in the way: retaining walls, railings and
the fence (hard barriers), hedges, benches and café seating (soft obstacles)
come from :mod:`amap_pipeline.graph.barriers`. :class:`WalkingArea` holds two
tiers: the *preferred* one keeps lines a stride off walls and out of every
obstacle; the *lenient* one only forbids crossing a wall, a hard barrier or
grazing a building, for links that have no other way.
"""

import heapq
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
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
# Preferred lines keep this far from building walls: the route ribbon (1.2 m
# half-width) then stays off the facade, Chaikin's ~0.35 m cut included.
LINE_CLEARANCE_M = 0.9
# Where a lane is too narrow for that, half of it still keeps lines centred.
SNUG_CLEARANCE_M = 0.45
# Off a retaining wall, a railing, a hedge or café seating, preferred lines
# keep this share of the wall clearance (the ribbon's edge may brush them).
BARRIER_SHARE = 2 / 3
# How far a detour may search around the straight line.
SEARCH_M = 45.0
# A spot standing in a soft obstacle (a panorama among café tables) leaves it
# by its nearest side: the obstacle opens round the spot this far past that.
EXIT_M = 1.5
# A node pushed out of a building may land this much further than the nearest
# spot outside, to stay on its own side of a wall or the fence.
SNAP_SLACK_M = 4.0


@dataclass(frozen=True, slots=True)
class Obstacles:
    """Building footprints and barriers, as the two kinds of test need them."""

    union: BaseGeometry  # footprints as mapped
    blocked: BaseGeometry  # what a line must not touch
    grown: BaseGeometry  # everything grown by CLEARANCE_M: detour corners
    # Hard barriers alone: a node snapped out of a building must not jump one.
    barriers: BaseGeometry = field(default_factory=Polygon)

    @classmethod
    def of(
        cls,
        footprints: BaseGeometry | Sequence[Polygon],
        hard: BaseGeometry | None = None,
        soft: BaseGeometry | None = None,
        wall_clearance_m: float = 0.0,
        barrier_clearance_m: float = 0.0,
    ) -> "Obstacles":
        """Lines must not cut ``footprints`` nor touch ``hard`` or ``soft``.

        With ``wall_clearance_m`` > 0 lines keep that far from buildings;
        otherwise they may graze them by ``GRAZE_M``. Barriers are thin
        (a wall is a line) and are never shrunk; ``barrier_clearance_m``
        keeps lines that far from them.
        """
        union = (
            footprints
            if isinstance(footprints, BaseGeometry)
            else unary_union(list(footprints))
        )
        walls = (
            union.buffer(wall_clearance_m, join_style="mitre", mitre_limit=2.0)
            if wall_clearance_m > 0
            else union.buffer(-GRAZE_M, join_style="mitre")
        )
        extra = [g for g in (hard, soft) if g is not None and not g.is_empty]
        kept = (
            [g.buffer(barrier_clearance_m, join_style="mitre") for g in extra]
            if barrier_clearance_m > 0
            else extra
        )
        blocked = unary_union([walls, *kept]) if kept else walls
        grown = (unary_union([union, *extra]) if extra else union).buffer(
            CLEARANCE_M, join_style="mitre", mitre_limit=2.0
        )
        barriers = hard if hard is not None else Polygon()
        for geometry in (union, blocked, grown, barriers):
            shapely.prepare(geometry)
        return cls(union=union, blocked=blocked, grown=grown, barriers=barriers)

    def crosses(self, a: XY, b: XY) -> bool:
        return bool(self.blocked.intersects(LineString([a, b])))

    def clear(self, path: Sequence[XY]) -> bool:
        return not any(self.crosses(p, q) for p, q in pairwise(path))


@dataclass(slots=True)
class WalkingArea:
    """The preferred and the lenient tier of what a walking line avoids.

    A spot that stands in a soft obstacle (a panorama among café tables, by
    a bench) is free to leave it, by its nearest side: the obstacle opens
    round the spot out to there (``EXIT_M``), and the rest of it is walked
    round as usual, not crossed.
    """

    footprints: BaseGeometry
    hard: BaseGeometry
    soft: list[Polygon]
    lenient: Obstacles
    # Buildings alone: a walk the tour proves (its photographer took it) where
    # the notebook has no opening in a wall or fence yet. Reported, not hidden.
    through_barriers: Obstacles
    # A line that changes level off every flight and ramp (barriers.leaks).
    leaks: Callable[[Sequence[XY]], bool] = lambda _path: False
    _tiers: dict[tuple[float, frozenset[tuple[int, XY]]], Obstacles] = field(
        default_factory=dict
    )

    @classmethod
    def of(
        cls,
        footprints: BaseGeometry | Sequence[Polygon],
        hard: BaseGeometry | None = None,
        soft: BaseGeometry | None = None,
        leaks: Callable[[Sequence[XY]], bool] | None = None,
    ) -> "WalkingArea":
        union = (
            footprints
            if isinstance(footprints, BaseGeometry)
            else unary_union(list(footprints))
        )
        hard = hard if hard is not None else Polygon()
        parts = [
            p
            for p in getattr(soft, "geoms", [soft] if soft is not None else [])
            if isinstance(p, Polygon) and not p.is_empty
        ]
        for part in parts:
            shapely.prepare(part)
        return cls(
            footprints=union,
            hard=hard,
            soft=parts,
            lenient=Obstacles.of(union, hard),
            through_barriers=Obstacles.of(union),
            leaks=leaks or (lambda _path: False),
        )

    def preferred(self, *ends: XY) -> Obstacles:
        """The preferred tier for a line between ``ends``."""
        return self._tier(LINE_CLEARANCE_M, ends)

    def snug(self, *ends: XY) -> Obstacles:
        """As preferred, half as far off walls (narrow lanes)."""
        return self._tier(SNUG_CLEARANCE_M, ends)

    def soft_for(self, *ends: XY) -> list[BaseGeometry]:
        """The soft obstacles a line between ``ends`` keeps out of."""
        return [
            part for part in map(self._opened(ends), range(len(self.soft)))
            if not part.is_empty
        ]  # fmt: skip

    def _inside(self, ends: Sequence[XY]) -> frozenset[tuple[int, XY]]:
        return frozenset(
            (i, (round(p[0], 2), round(p[1], 2)))
            for i, part in enumerate(self.soft)
            for p in ends
            if part.intersects(Point(p))
        )

    def _opened(self, ends: Sequence[XY]) -> Callable[[int], BaseGeometry]:
        inside = self._inside(ends)

        def opened(i: int) -> BaseGeometry:
            part: BaseGeometry = self.soft[i]
            for j, p in inside:
                if j == i:
                    spot = Point(p)
                    reach = self.soft[i].exterior.distance(spot) + EXIT_M
                    part = part.difference(spot.buffer(reach))
            return part

        return opened

    def _tier(self, clearance_m: float, ends: Sequence[XY]) -> Obstacles:
        key = (clearance_m, self._inside(ends))
        if key not in self._tiers:
            soft = self.soft_for(*ends)
            self._tiers[key] = Obstacles.of(
                self.footprints,
                self.hard,
                unary_union(soft) if soft else None,
                wall_clearance_m=clearance_m,
                barrier_clearance_m=clearance_m * BARRIER_SHARE,
            )
        return self._tiers[key]


def snap_point(p: XY, obstacles: Obstacles, margin_m: float = CLEARANCE_M) -> XY:
    """``p`` if clear of every building, else just outside the nearest wall."""
    point = Point(p)
    if obstacles.union.distance(
        point
    ) >= margin_m * 0.5 and not obstacles.union.contains(point):
        return p
    # The nearest point on the clearance-grown outline is outside and clear,
    # unless reaching it jumps a wall or the fence (another level, the
    # street): then the nearest one on this side, a little further round.
    boundary = obstacles.grown.boundary
    nearest = nearest_points(boundary, point)[0]
    candidates = [(nearest.x, nearest.y)]
    if obstacles.barriers.intersects(LineString([p, candidates[0]])):
        reach = point.distance(nearest) + SNAP_SLACK_M
        local = boundary.intersection(point.buffer(reach))
        candidates = sorted(
            (
                (float(x), float(y))
                for line in getattr(local, "geoms", [local])
                if isinstance(line, LineString)
                for x, y in line.segmentize(0.25).coords
            ),
            key=lambda c: math.dist(c, p),
        )
    for target in candidates:
        # Nudge a hair further out so the result is not on the boundary.
        dx, dy = target[0] - p[0], target[1] - p[1]
        length = math.hypot(dx, dy) or 1.0
        snapped = (target[0] + dx / length * 0.05, target[1] + dy / length * 0.05)
        if not obstacles.barriers.intersects(LineString([p, snapped])):
            return snapped
    return p


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
        # Holes too: a yard ringed by walls is walked round on the inside.
        for ring in (simple.exterior, *simple.interiors):
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
