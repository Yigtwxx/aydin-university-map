"""What a walker cannot cross besides buildings: the furniture notebook's.

The walking graph keeps out of building footprints
(:mod:`amap_pipeline.graph.clearance`); this module adds the rest of the
campus that a route must not be drawn through, in two tiers:

- **hard** barriers no line may cross: retaining walls where the ground
  changes level (a terrace's ``wall`` edge, opened where a flight or ramp
  meets it), free-standing railings and the boundary fence (gates are the
  gaps between its runs), and pools;
- **soft** obstacles a line keeps clear of whenever a reasonable walk round
  exists: hedges, planters, benches, kiosks, the statue and the like, café
  seating areas and flowerbeds.

Raised walkways (a slab on columns, a footbridge) are a level of their own
(:class:`Deck`): what stands below them is no barrier up there, and their
balustrades are none down below.

Every shape is in local metres (x east, y north), like the graph's ``enu``.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import shapely
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from amap_contracts.furniture import (
    Edge,
    FurnitureCollection,
    Item,
    ItemKind,
    Ramp,
    Stairs,
    Terrace,
    Walkway,
)
from amap_pipeline.graph.clearance import Obstacles

XY = tuple[float, float]

# A level change lower than this is a kerb or a gentle step, not a wall.
WALL_MIN_STEP_M = 0.4
# Half the thickness given to wall and railing lines (they have none).
WALL_HALF_M = 0.15
RAILING_HALF_M = 0.2
# A flight or ramp opens its wall this much wider than itself, and this far
# past its foot and top (flights stand outside the terraces they join).
OPENING_SIDE_M = 0.3
OPENING_END_M = 1.0
# Wall outlines are tested for a level change every this many metres.
WALL_PIECE_M = 1.0
# How far outside a wall its lower (or higher) ground is looked up.
WALL_PROBE_M = 0.5
# Lines are checked for a change of level every this many metres, and may
# climb only this close to a flight or ramp.
LEVEL_STEP_M = 0.5
CLIMB_MARGIN_M = 1.0
# A terrace outline drawn this close to a building, along its facade, is the
# building's own edge (the strip between is nobody's ground): no wall there.
FACADE_M = 1.6
FACADE_MAX_ANGLE_DEG = 25.0
# A raised walk meets a flight's top, a terrace at its height or its own
# balustrade within this; seams this wide between its pieces are closed.
DECK_JOIN_M = 1.0
# Walks up there keep this far off its edge and what stands on it.
DECK_CLEARANCE_M = 0.5

# Footprint (length across the heading, depth along it) of the items a walker
# goes round; mirrors itemGeometry/DEFAULT_LENGTH in
# apps/web/src/features/campus/furnitureGeometry.ts. Round ones use a circle
# of the length's diameter. Lamps, bins, bollards, flagpoles, signs and the
# like are too slight to bend a route.
_ITEM_SIZE: dict[ItemKind, tuple[float, float]] = {
    ItemKind.BENCH: (1.8, 0.5),
    ItemKind.PLANTER: (0.8, 0.7),
    ItemKind.HEDGE: (2.0, 0.62),
    ItemKind.KIOSK: (1.5, 1.0),
    ItemKind.BOOTH: (1.7, 1.7),
    ItemKind.LETTERS: (4.2, 0.5),
    ItemKind.STATUE: (0.9, 2.2),
}
_ROUND_ITEMS: dict[ItemKind, float] = {
    ItemKind.EMBLEM: 4.5,
    ItemKind.TOPIARY: 0.9,
}
# Kinds of greenery.json areas a walker goes round.
SOFT_AREA_KINDS = frozenset({"flowerbed"})
HARD_AREA_KINDS = frozenset({"pool"})


@dataclass(frozen=True, slots=True)
class Barriers:
    """Hard barriers (never crossed) and soft obstacles (kept clear of).

    ``levels`` and ``climbs`` (flights and ramps) catch what the walls miss:
    a line may change level only on a flight or a ramp (:meth:`leaks`).
    """

    hard: BaseGeometry
    soft: BaseGeometry
    levels: tuple["_Level", ...] = ()
    climbs: BaseGeometry = field(default_factory=Polygon)
    decks: tuple["Deck", ...] = ()

    @classmethod
    def none(cls) -> "Barriers":
        return cls(hard=Polygon(), soft=Polygon())

    def leaks(self, path: Sequence[XY]) -> bool:
        """Whether ``path`` changes level off every flight and ramp.

        Walls stand where the notebook draws a terrace's edge; one folded
        into a building (:func:`wall_lines`) or opened beside a flight
        leaves a gap a line could slip through to another level. Levels are
        compared only between surveyed terraces (the streets have none).
        """
        if not self.levels or len(path) < 2:
            return False
        line = LineString(path)
        steps = max(1, math.ceil(line.length / LEVEL_STEP_M))
        previous: tuple[float, Point] | None = None
        for k in range(steps + 1):
            point = line.interpolate(line.length * k / steps)
            z = surveyed_level(self.levels, (point.x, point.y))
            if z is None:
                previous = None
                continue
            if previous is not None and abs(z - previous[0]) > WALL_MIN_STEP_M:
                mid = Point(
                    (point.x + previous[1].x) / 2, (point.y + previous[1].y) / 2
                )
                if not self.climbs.contains(mid):
                    return True
            previous = (z, point)
        return False


@dataclass(frozen=True, slots=True)
class Deck:
    """A raised walkway, with the terraces at its height it opens onto.

    A walk between two spots up here stays on ``floor``, whatever the ground
    below has (walls, the fence, a sunken hall); it reaches the ground only
    down one of the ``landings``, the flights and ramps whose top meets it.
    """

    id: str
    z: float
    spots: frozenset[str]
    floor: BaseGeometry
    # Terraces at the deck's height: a spot on one walks on to the deck.
    ground: BaseGeometry
    landings: tuple[Stairs | Ramp, ...]
    # Everything off the floor, as walk_around needs it.
    inside: Obstacles

    def holds(self, p: XY) -> bool:
        """A spot standing on a terrace at the deck's height, on its floor."""
        point = Point(p)
        return bool(self.ground.covers(point) and self.floor.covers(point))


@dataclass(frozen=True, slots=True)
class _Level:
    terrace: Terrace
    polygon: Polygon
    area: float


def _polygon(ring: Sequence[XY]) -> Polygon | None:
    polygon = Polygon(ring)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if not isinstance(polygon, Polygon) or polygon.area <= 1e-6:
        return None
    return polygon


def surveyed_level(levels: Sequence[_Level], p: XY) -> float | None:
    """The innermost terrace's height at ``p``; None outside every terrace."""
    point = Point(p)
    best: _Level | None = None
    for level in levels:
        if level.polygon.contains(point) and (best is None or level.area < best.area):
            best = level
    return best.terrace.z_m if best is not None else None


def level_at(levels: Sequence[_Level], p: XY) -> float:
    """Ground height at ``p``: the innermost terrace holding it, else 0.

    Mirrors ``heightAt`` in apps/web/src/features/campus/terrain.ts (without
    flights and banks, which are not walls).
    """
    point = Point(p)
    best: _Level | None = None
    for level in levels:
        if level.polygon.contains(point) and (best is None or level.area < best.area):
            best = level
    return best.terrace.z_m if best is not None else 0.0


def _levels(terraces: Iterable[Terrace]) -> list[_Level]:
    levels: list[_Level] = []
    for terrace in terraces:
        polygon = _polygon(terrace.outline)
        if polygon is not None:
            levels.append(_Level(terrace, polygon, polygon.area))
    return levels


def _pieces(ring: Sequence[XY]) -> Iterable[tuple[XY, XY]]:
    """The closed ring cut into pieces of at most ``WALL_PIECE_M``."""
    closed = [*ring, ring[0]] if ring[0] != ring[-1] else list(ring)
    for a, b in pairwise(closed):
        length = math.dist(a, b)
        count = max(1, math.ceil(length / WALL_PIECE_M))
        for k in range(count):
            t0, t1 = k / count, (k + 1) / count
            yield (
                (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1),
            )


def _along_facade(a: XY, b: XY, footprints: BaseGeometry | None) -> bool:
    """A wall piece running beside a building's facade, close to it."""
    if footprints is None or footprints.is_empty:
        return False
    da = footprints.distance(Point(a))
    db = footprints.distance(Point(b))
    if max(da, db) > FACADE_M:
        return False
    # Parallel: both ends about as far out (a wall meeting it head-on is not).
    return abs(da - db) <= math.dist(a, b) * math.sin(
        math.radians(FACADE_MAX_ANGLE_DEG)
    )


def wall_lines(
    terraces: Sequence[Terrace], footprints: BaseGeometry | None = None
) -> BaseGeometry:
    """Where a ``wall``-edged terrace drops (or rises) to the ground beside it.

    Each piece of the outline is a wall when the level just inside and just
    outside it differ by more than ``WALL_MIN_STEP_M``; the outside level is
    whatever terrace holds that spot (a sibling, the parent, or the street).
    Pieces drawn along a building's facade (``FACADE_M``) are the building's
    edge, which the graph keeps clear of anyway; a wall there would only cut
    off the doors in front of it.
    """
    levels = _levels(terraces)
    walls: list[LineString] = []
    for level in levels:
        if level.terrace.edge is not Edge.WALL:
            continue
        for a, b in _pieces(level.terrace.outline):
            length = math.dist(a, b)
            if length < 1e-6:
                continue
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            nx, ny = (b[1] - a[1]) / length, -(b[0] - a[0]) / length
            left = (mid[0] + nx * WALL_PROBE_M, mid[1] + ny * WALL_PROBE_M)
            right = (mid[0] - nx * WALL_PROBE_M, mid[1] - ny * WALL_PROBE_M)
            inside, outside = (
                (left, right) if level.polygon.contains(Point(left)) else (right, left)
            )
            step = abs(level_at(levels, inside) - level_at(levels, outside))
            if step > WALL_MIN_STEP_M and not _along_facade(a, b, footprints):
                walls.append(LineString([a, b]))
    return unary_union(walls) if walls else MultiLineString()


def opening(flight: Stairs | Ramp) -> Polygon:
    """The gap a flight or ramp makes in the walls it climbs."""
    (fx, fy), (tx, ty) = flight.foot, flight.top
    length = math.dist(flight.foot, flight.top) or 1.0
    ux, uy = (tx - fx) / length, (ty - fy) / length
    line = LineString(
        [
            (fx - ux * OPENING_END_M, fy - uy * OPENING_END_M),
            (tx + ux * OPENING_END_M, ty + uy * OPENING_END_M),
        ]
    )
    return line.buffer(flight.width_m / 2 + OPENING_SIDE_M, cap_style="flat")


def item_footprint(item: Item) -> Polygon | None:
    """What an item covers on the ground, or None if a walker brushes past."""
    x, y = item.at
    if item.kind in _ROUND_ITEMS:
        diameter = item.length_m or _ROUND_ITEMS[item.kind]
        return Point(x, y).buffer(diameter / 2, quad_segs=8)
    if item.kind not in _ITEM_SIZE:
        return None
    default_length, depth = _ITEM_SIZE[item.kind]
    # Statue: length_m is never given; its body runs along the heading.
    length = item.length_m or default_length
    h = math.radians(item.heading_deg)
    fx, fy = math.sin(h), math.cos(h)  # the way it faces
    ax, ay = fy, -fx  # across the heading: its length
    hl, hd = length / 2, depth / 2
    return Polygon(
        [
            (x + ax * hl + fx * hd, y + ay * hl + fy * hd),
            (x - ax * hl + fx * hd, y - ay * hl + fy * hd),
            (x - ax * hl - fx * hd, y - ay * hl - fy * hd),
            (x + ax * hl - fx * hd, y + ay * hl - fy * hd),
        ]
    )


def _deck(
    walkway: Walkway,
    terraces: Sequence[_Level],
    flights: Sequence[Stairs | Ramp],
    footprints: BaseGeometry | None,
) -> Deck | None:
    raised = _polygon(walkway.outline)
    if raised is None:
        return None
    level = [
        t.polygon
        for t in terraces
        if abs(t.terrace.z_m - walkway.z_m) <= WALL_MIN_STEP_M
        and t.polygon.distance(raised) <= DECK_JOIN_M
    ]
    ground = unary_union(level) if level else Polygon()
    reach = unary_union([raised, ground])
    landings = tuple(
        f
        for f in flights
        if abs(f.base_z + f.rise_m - walkway.z_m) <= WALL_MIN_STEP_M
        and reach.distance(Point(f.top)) <= DECK_JOIN_M
    )
    joined = unary_union([reach, *(Point(f.top).buffer(DECK_JOIN_M) for f in landings)])
    # Close the seams where the slab meets the deck (both drawn to +-0.5 m).
    floor = joined.buffer(DECK_JOIN_M / 2, join_style="mitre").buffer(
        -DECK_JOIN_M / 2, join_style="mitre"
    )
    holes: list[BaseGeometry] = [
        h for h in map(_polygon, walkway.holes) if h is not None
    ]
    if footprints is not None:
        holes.append(footprints)
    floor = floor.difference(unary_union(holes)) if holes else floor
    off = floor.envelope.buffer(DECK_JOIN_M * 10).difference(floor)
    grown = off.buffer(DECK_CLEARANCE_M, join_style="mitre", mitre_limit=2.0)
    for geometry in (floor, ground, off, grown):
        shapely.prepare(geometry)
    return Deck(
        id=walkway.id,
        z=walkway.z_m,
        spots=frozenset(walkway.spots),
        floor=floor,
        ground=ground,
        landings=landings,
        inside=Obstacles(union=off, blocked=off, grown=grown),
    )


def _on_walkway(line: Sequence[XY], base_z: float, walkways: Sequence[Walkway]) -> bool:
    """A railing up on a walkway's edge (its balustrade, not the ground's)."""
    for walkway in walkways:
        raised = _polygon(walkway.outline)
        if (
            raised is not None
            and abs(base_z - walkway.z_m) <= WALL_MIN_STEP_M
            and LineString(line).distance(raised) <= DECK_JOIN_M
        ):
            return True
    return False


def build_barriers(
    furniture: FurnitureCollection,
    greenery_areas: Iterable[dict[str, Any]] = (),
    footprints: BaseGeometry | None = None,
) -> Barriers:
    """Hard and soft barriers from the furniture notebook and greenery areas.

    ``footprints`` (the buildings the graph avoids) lets walls drawn along
    a facade fold into the building.
    """
    openings = unary_union([opening(f) for f in [*furniture.stairs, *furniture.ramps]])
    walls = wall_lines(furniture.terraces, footprints).difference(openings)
    hard: list[BaseGeometry] = [walls.buffer(WALL_HALF_M, cap_style="flat")]
    hard.extend(
        LineString(r.line).buffer(RAILING_HALF_M, cap_style="flat")
        for r in furniture.railings
        if not _on_walkway(r.line, r.base_z, furniture.walkways)
    )
    soft: list[BaseGeometry] = []
    for area in greenery_areas:
        polygon = _polygon([tuple(p) for p in area["outline"]])
        if polygon is None:
            continue
        if area["kind"] in HARD_AREA_KINDS:
            hard.append(polygon)
        elif area["kind"] in SOFT_AREA_KINDS:
            soft.append(polygon)
    soft.extend(f for f in map(item_footprint, furniture.items) if f is not None)
    soft.extend(
        p for p in (_polygon(s.outline) for s in furniture.seating) if p is not None
    )
    flights = [*furniture.stairs, *furniture.ramps]
    climbs = unary_union(
        [
            LineString([f.foot, f.top]).buffer(f.width_m / 2 + CLIMB_MARGIN_M)
            for f in flights
        ]
    )
    shapely.prepare(climbs)
    levels = _levels(furniture.terraces)
    decks = (_deck(w, levels, flights, footprints) for w in furniture.walkways)
    return Barriers(
        hard=unary_union(hard),
        soft=unary_union(soft),
        levels=tuple(levels),
        climbs=climbs,
        decks=tuple(d for d in decks if d is not None),
    )
