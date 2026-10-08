"""Build the metric walking graph from georeferenced panoramas.

Nodes are panoramas with a georeferenced SfM pose. Edges come from two sources:

- **tour** links of the 360 tour whose both ends are posed, kept only if they
  are physically walkable: no longer than ``max_link_m`` (longer ones are
  teleports to distant buildings) and never through a building: a link that
  would cut a footprint follows the shortest line around it instead
  (``Edge.path_enu``), or is dropped when that detour is unreasonable;
- **inferred** links between outdoor panoramas closer than ``infer_radius_m``
  with a clear line of sight (or a short bend round one building corner),
  which densifies the sparse tour network so routes take the direct line
  across open ground instead of hopping between tour hotspots.

Nodes standing inside a footprint (SfM vs OSM disagreement) are first moved
just outside its nearest wall (:mod:`amap_pipeline.graph.clearance`). Only
indoor panoramas may be inside buildings.

Besides buildings, lines keep out of the furniture notebook's barriers
(:mod:`amap_pipeline.graph.barriers`): a retaining wall is climbed only where
a flight or ramp opens it, the fence is passed only at its gates, and hedges,
benches and café seating are walked round when that costs little (a tour
link with no such walk keeps the shorter line through them). A spot up on a
raised walkway (:class:`~amap_pipeline.graph.barriers.Deck`) walks along its
floor, and to the ground only down a flight or ramp that meets it.

Islands of the measured network (SfM models no tour link joins) are bridged
to the main one by the shortest reasonable walk outside, if there is one.

Indoor panoramas without a pose then hang off this network through the
tour's links (:mod:`amap_pipeline.graph.indoor`), with estimated lengths.

Lengths are 3D distances between camera centres (local metres), measured
along the detour when there is one.
"""

import itertools
import math
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import numpy as np
from scipy.spatial import KDTree
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from amap_contracts import CAMPUS_ORIGIN_LAT, CAMPUS_ORIGIN_LNG
from amap_contracts.graph import (
    WALKING_SPEED_MPS,
    Edge,
    EdgeCrossing,
    EdgeKind,
    EdgeOrigin,
    Graph,
    GraphMeta,
    LengthSource,
    LocalizedText,
    Node,
    NodeKind,
    PoseSource,
)
from amap_pipeline.graph.barriers import Barriers, Deck
from amap_pipeline.graph.clearance import (
    Obstacles,
    WalkingArea,
    path_length,
    snap_point,
    walk_around,
)
from amap_pipeline.graph.indoor import IndoorReport, attach_indoor, position_of

_BLOCK_RE = re.compile(r"\b([A-Z](?:-[A-Z])?) Blok\b")
DOORWAY_KINDS = frozenset({NodeKind.ENTRANCE, NodeKind.INDOOR})
METRES_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True, slots=True)
class GraphParams:
    max_link_m: float = 60.0
    infer_radius_m: float = 35.0
    # A detour around buildings may be this much longer than the straight
    # link (ratio, or metres for short links, whichever allows more).
    max_detour_ratio: float = 1.6
    max_detour_extra_m: float = 25.0
    # A longer tour link through a building is a hotspot to another block's
    # door (a teleport through the interior), not a walk round the corner.
    max_detour_link_m: float = 30.0
    # Inferred links may bend round a building corner when that costs little.
    corner_ratio: float = 1.2
    corner_vertices: int = 2
    # The walk round soft obstacles (hedges, café seating) and a stride off
    # walls is taken over the shortest allowed line when it is at most this
    # much longer (ratio, or metres, whichever allows more).
    # 12 m: about what crossing costs a route (CROSSING_S in the API's router).
    soft_detour_ratio: float = 1.25
    soft_detour_extra_m: float = 12.0
    # Hang indoor panoramas off the network through the tour's links.
    indoor: bool = True
    # An island of the measured network joins the main one by a walk outside
    # at most this far (straight line), round buildings as tour links do.
    bridge_max_m: float = 120.0
    # Up to this many bridges per island, to spots this far apart, no more
    # than this much longer than the shortest.
    bridge_count: int = 3
    bridge_spread_m: float = 20.0
    bridge_spread_ratio: float = 1.5
    # A tour link passing this close to another measured spot walks past it:
    # the link is split there (the route can stop at it, not turn back).
    pass_by_m: float = 1.0
    # ...and this far from either end (closer, it is that end's own spot).
    pass_by_end_m: float = 3.0
    # An inferred link down a raised deck's landing may be this much longer
    # than the straight line (tour links: the usual detour allowance).
    landing_detour_m: float = 12.0


@dataclass(slots=True)
class BuildReport:
    tour_links_kept: int = 0
    inferred_links: int = 0
    dropped: dict[str, list[str]] = field(
        default_factory=lambda: {
            "teleport": [],
            "crosses_building": [],
            "unposed": [],
            # A tour link between a raised walkway and the ground with no
            # flight or ramp between them (the slab's lift, another bridge).
            "off_deck": [],
        }
    )
    snapped: dict[str, float] = field(default_factory=dict)  # node -> metres moved
    # Nodes left inside a building: moving them out would jump a wall/fence.
    unsnapped: list[str] = field(default_factory=list)
    # Drawn edges that could not keep clear of soft obstacles or wall margins.
    soft_fallback: list[str] = field(default_factory=list)
    # Drawn edges over a wall or the fence: tour walks the notebook has no
    # opening for yet (a missing flight or gate to survey).
    barrier_fallback: list[str] = field(default_factory=list)
    detoured: list[str] = field(default_factory=list)
    bridged: list[str] = field(default_factory=list)  # islands joined outside
    shortcuts: list[str] = field(default_factory=list)  # hooks cut short
    passed_by: list[str] = field(default_factory=list)  # "a|b via m"
    indoor: IndoorReport = field(default_factory=IndoorReport)


def building_of(label: str) -> str | None:
    match = _BLOCK_RE.search(label)
    return match.group(1) if match else None


def make_nodes(
    posed: Mapping[str, Mapping[str, Any]], scenes: Mapping[str, Mapping[str, Any]]
) -> list[Node]:
    """``posed``: scene -> georef record (lat, lng, x, y, height_m, heading_deg)."""
    nodes: list[Node] = []
    for scene, pose in posed.items():
        meta = scenes[scene]
        nodes.append(
            Node(
                id=scene,
                kind=NodeKind(meta["kind"]),
                lat=float(pose["lat"]),
                lng=float(pose["lng"]),
                alt_m=float(pose["height_m"]),
                enu=(float(pose["x"]), float(pose["y"]), float(pose["height_m"])),
                heading_deg=float(pose["heading_deg"]) % 360.0,
                pose_source=PoseSource(pose.get("pose_source", PoseSource.SFM)),
                label=LocalizedText(tr=meta["label"]["tr"], en=meta["label"]["en"]),
                area=LocalizedText(tr=meta["area"]["tr"], en=meta["area"]["en"]),
                # A block set in configs/scene_overrides.toml wins over the label.
                building=meta.get("block") or building_of(meta["label"]["tr"]),
            )
        )
    return nodes


def _edge_kind(a: Node, b: Node) -> EdgeKind:
    kinds = {a.kind, b.kind}
    if kinds == {NodeKind.INDOOR}:
        return EdgeKind.INDOOR
    if kinds & DOORWAY_KINDS:
        return EdgeKind.ENTRANCE
    return EdgeKind.OUTDOOR


def _edge(
    a: Node, b: Node, origin: EdgeOrigin, path: list[tuple[float, float]] | None = None
) -> Edge:
    first, second = sorted((a, b), key=lambda n: n.id)
    if path is not None and first is not a:
        path = path[::-1]
    dz = first.enu[2] - second.enu[2]
    if path is not None and len(path) > 2:
        length = math.hypot(path_length(path), dz)
        path_enu: list[tuple[float, float]] | None = [
            (round(x, 2), round(y, 2)) for x, y in path
        ]
    else:
        length = float(np.linalg.norm(np.subtract(first.enu, second.enu)))
        path_enu = None
    return Edge(
        id=f"{first.id}|{second.id}",
        source=first.id,
        target=second.id,
        kind=_edge_kind(first, second),
        origin=origin,
        length_m=max(length, 0.01),
        cost_s=max(length, 0.01) / WALKING_SPEED_MPS,
        length_source=LengthSource.SFM,
        path_enu=path_enu,
    )


def _xy(node: Node) -> tuple[float, float]:
    return (node.enu[0], node.enu[1])


def snap_nodes(
    nodes: list[Node], obstacles: Obstacles, report: BuildReport
) -> list[Node]:
    """Move outdoor and entrance nodes out of buildings (indoor ones stay)."""
    snapped: list[Node] = []
    for node in nodes:
        if node.kind == NodeKind.INDOOR:
            snapped.append(node)
            continue
        x, y = snap_point(_xy(node), obstacles)
        dx, dy = x - node.enu[0], y - node.enu[1]
        if dx == 0.0 and dy == 0.0:
            if obstacles.union.contains(Point(x, y)):
                report.unsnapped.append(node.id)
            snapped.append(node)
            continue
        report.snapped[node.id] = round(math.hypot(dx, dy), 2)
        # A few metres: a local tangent plane is exact to millimetres.
        lat = node.lat + dy / METRES_PER_DEG_LAT
        lng = node.lng + dx / (METRES_PER_DEG_LAT * math.cos(math.radians(node.lat)))
        snapped.append(
            node.model_copy(update={"enu": (x, y, node.enu[2]), "lat": lat, "lng": lng})
        )
    return snapped


def _walk(
    a: tuple[float, float],
    b: tuple[float, float],
    obstacles: Obstacles,
    params: GraphParams,
    bends_ok: bool,
) -> list[tuple[float, float]] | None:
    straight = math.dist(a, b)
    path = walk_around(a, b, obstacles)
    allowed = max(
        straight * params.max_detour_ratio, straight + params.max_detour_extra_m
    )
    bends = len(path or []) > 2
    if path is None or path_length(path) > allowed:
        return None
    if bends and not bends_ok and straight > params.max_detour_link_m:
        return None
    return path


def outdoor_line(
    a: tuple[float, float],
    b: tuple[float, float],
    area: WalkingArea,
    params: GraphParams,
    bends_ok: bool = False,
    through_barriers: bool = False,
) -> list[tuple[float, float]] | None:
    """The walk outside from a to b, round obstacles; None when unreasonable.

    A detour may be ``max_detour_ratio`` longer (or ``max_detour_extra_m``
    for short links); a long link that has to bend at all is a teleport to
    another block's door unless ``bends_ok`` (island bridges look for walks).

    The shortest line that crosses no building, wall or fence is the bound;
    the walk that also keeps a stride off walls (or half one, in a narrow
    lane) and goes round hedges and seating replaces it when that costs at
    most ``soft_detour_ratio``/``soft_detour_extra_m``.

    ``through_barriers``: a walk known to exist (a tour link, a bridge) that
    finds no opening in a wall or the fence keeps the line round buildings
    alone; the notebook lacks that flight or gate, and the export lists it.
    """
    lenient = _walk(a, b, area.lenient, params, bends_ok)
    if lenient is not None and area.leaks(lenient):
        lenient = None
    if lenient is None:
        if through_barriers:
            return _walk(a, b, area.through_barriers, params, bends_ok)
        return None
    bound = path_length(lenient)
    allowed = max(bound * params.soft_detour_ratio, bound + params.soft_detour_extra_m)
    for tier in (area.preferred(a, b), area.snug(a, b)):
        path = _walk(a, b, tier, params, bends_ok)
        if path is not None and path_length(path) <= allowed and not area.leaks(path):
            return path
    return lenient


def inferred_line(
    a: tuple[float, float],
    b: tuple[float, float],
    area: WalkingArea,
    params: GraphParams,
) -> list[tuple[float, float]] | None:
    """A densifying line: in clear sight, a stride off walls (half one in a
    narrow lane), or a short bend round a corner; no lenient fallback (tour
    links carry that)."""
    straight = math.dist(a, b)
    for tier in (area.preferred(a, b), area.snug(a, b)):
        if not tier.crosses(a, b) and not area.leaks([a, b]):
            return [a, b]
        # Round the corner of a block instead of visiting a door to turn.
        path = walk_around(a, b, tier)
        if (
            path is not None
            and len(path) <= 2 + params.corner_vertices
            and path_length(path) <= straight * params.corner_ratio
            and not area.leaks(path)
        ):
            return path
    return None


def deck_spots(barriers: Barriers | None) -> dict[str, Deck]:
    """Spot -> the raised walkway it was taken up on."""
    decks = barriers.decks if barriers is not None else ()
    return {spot: deck for deck in decks for spot in deck.spots}


def _within_detour(
    path: Sequence[tuple[float, float]], straight: float, params: GraphParams
) -> bool:
    allowed = max(
        straight * params.max_detour_ratio, straight + params.max_detour_extra_m
    )
    return path_length(path) <= allowed


def _deck_walk(
    a: tuple[float, float],
    b: tuple[float, float],
    deck: Deck,
    params: GraphParams,
    inferred: bool,
) -> list[tuple[float, float]] | None:
    path = walk_around(a, b, deck.inside)
    if path is None:
        return None
    straight = math.dist(a, b)
    if inferred:
        corner = (
            len(path) <= 2 + params.corner_vertices
            and path_length(path) <= straight * params.corner_ratio
        )
        return path if corner else None
    return path if _within_detour(path, straight, params) else None


def _down_landing(
    a: tuple[float, float],
    b: tuple[float, float],
    deck: Deck,
    area: WalkingArea,
    params: GraphParams,
    inferred: bool,
) -> list[tuple[float, float]] | None:
    """From ``a`` up on the deck down its nearest-going landing to ``b``."""
    best: list[tuple[float, float]] | None = None
    for flight in deck.landings:
        upper = walk_around(a, flight.top, deck.inside)
        if upper is None:
            continue
        lower = (
            inferred_line(flight.foot, b, area, params)
            if inferred
            else outdoor_line(flight.foot, b, area, params)
        )
        if lower is None:
            continue
        path = [*upper, *lower]
        if best is None or path_length(path) < path_length(best):
            best = path
    straight = math.dist(a, b)
    if best is None or not _within_detour(best, straight, params):
        return None
    if inferred and path_length(best) > straight + params.landing_detour_m:
        return None
    return best


def deck_line(
    a: Node,
    b: Node,
    decks: Mapping[str, Deck],
    area: WalkingArea,
    params: GraphParams,
    inferred: bool = False,
) -> list[tuple[float, float]] | None:
    """The walk between two spots, one of them up on a raised walkway.

    Both up there (or the other on a terrace the deck opens onto): along its
    floor. The other on the ground: down whichever landing makes the shorter
    walk, then as any line outside. Two walkways that do not meet: none (the
    walk goes down and up again through other spots).
    """
    if a.id in decks and b.id in decks and decks[a.id] is not decks[b.id]:
        return None
    flip = a.id not in decks
    up, other = (b, a) if flip else (a, b)
    deck = decks[up.id]
    start, end = _xy(up), _xy(other)
    if other.id in deck.spots or deck.holds(end):
        path = _deck_walk(start, end, deck, params, inferred)
    else:
        path = _down_landing(start, end, deck, area, params, inferred)
    if path is None:
        return None
    return path[::-1] if flip else path


def _deck_ground(
    path: Sequence[tuple[float, float]], a: Node, b: Node, decks: Mapping[str, Deck]
) -> tuple[bool, list[tuple[float, float]]]:
    """A drawn deck edge: whether its part up there stays on the floor, and
    its part on the ground (empty when it never comes down)."""
    if a.id in decks and b.id in decks and decks[a.id] is not decks[b.id]:
        return False, []
    points = list(path) if a.id in decks else list(path)[::-1]
    deck = decks[a.id] if a.id in decks else decks[b.id]
    for i, (p, q) in enumerate(pairwise(points)):
        for flight in deck.landings:
            if math.dist(p, flight.top) <= 0.05 and math.dist(q, flight.foot) <= 0.05:
                return deck.inside.clear(points[: i + 1]), points[i + 1 :]
    return deck.inside.clear(points), []


def walked_past(
    tour_links: Iterable[tuple[str, str]],
    by_id: Mapping[str, Node],
    params: GraphParams,
    report: BuildReport,
    area: WalkingArea,
    up: Collection[str] = frozenset(),
) -> list[tuple[str, str]]:
    """Tour links, each split at the measured spots it passes on its way.

    The photographer walking from one panorama to the next passes others on
    the line between: a route to such a spot stops there instead of walking
    on to the far end and coming back. Only a link walked straight counts
    (no teleport, no line through a building, which is walked round). Spots
    ``up`` on a raised walkway pass nothing below them, nor are passed.
    """
    walkers = [
        n
        for n in by_id.values()
        if n.kind in (NodeKind.OUTDOOR, NodeKind.ENTRANCE) and n.id not in up
    ]
    out: list[tuple[str, str]] = []
    for a_id, b_id in tour_links:
        a, b = by_id.get(a_id), by_id.get(b_id)
        if (
            a is None
            or b is None
            or a_id in up
            or b_id in up
            or not {a.kind, b.kind}
            <= {
                NodeKind.OUTDOOR,
                NodeKind.ENTRANCE,
            }
        ):
            out.append((a_id, b_id))
            continue
        line = LineString([_xy(a), _xy(b)])
        length = line.length
        if length > params.max_link_m or not area.through_barriers.clear(
            [_xy(a), _xy(b)]
        ):
            out.append((a_id, b_id))
            continue
        on_way = sorted(
            (line.project(Point(_xy(m))), m.id)
            for m in walkers
            if m.id not in (a_id, b_id)
            and length > 0
            and line.distance(Point(_xy(m))) <= params.pass_by_m
            and params.pass_by_end_m
            < line.project(Point(_xy(m)))
            < length - params.pass_by_end_m
        )
        if not on_way:
            out.append((a_id, b_id))
            continue
        chain = [a_id, *(m for _, m in on_way), b_id]
        out.extend(pairwise(chain))
        passed = (
            f"{'|'.join(sorted((a_id, b_id)))} via {', '.join(m for _, m in on_way)}"
        )
        if passed not in report.passed_by:  # links are listed from both ends
            report.passed_by.append(passed)
    return out


def walking_area(
    footprints: BaseGeometry, barriers: Barriers | None = None
) -> WalkingArea:
    barriers = barriers if barriers is not None else Barriers.none()
    return WalkingArea.of(footprints, barriers.hard, barriers.soft, barriers.leaks)


def make_edges(
    nodes: list[Node],
    tour_links: Iterable[tuple[str, str]],
    footprints: BaseGeometry,
    params: GraphParams = GraphParams(),  # noqa: B008 - frozen dataclass
    report: BuildReport | None = None,
    barriers: Barriers | None = None,
) -> tuple[list[Edge], BuildReport]:
    by_id = {n.id: n for n in nodes}
    area = walking_area(footprints, barriers)
    decks = deck_spots(barriers)
    report = report if report is not None else BuildReport()
    edges: dict[str, Edge] = {}

    seen: set[str] = set()
    for a_id, b_id in walked_past(tour_links, by_id, params, report, area, decks):
        key = "|".join(sorted((a_id, b_id)))
        if key in seen:  # links are listed from both ends
            continue
        seen.add(key)
        if a_id not in by_id or b_id not in by_id:
            report.dropped["unposed"].append(key)
            continue
        a, b = by_id[a_id], by_id[b_id]
        if _edge(a, b, EdgeOrigin.TOUR).length_m > params.max_link_m:
            report.dropped["teleport"].append(key)
            continue
        if NodeKind.INDOOR in (a.kind, b.kind):
            # Indoor panoramas are inside by definition: a walk through the
            # building, never a line to draw outside.
            edges[key] = _edge(a, b, EdgeOrigin.TOUR).model_copy(
                update={"passage": True}
            )
            report.tour_links_kept += 1
            continue
        if a.id in decks or b.id in decks:
            path = deck_line(a, b, decks, area, params)
            if path is None:
                report.dropped["off_deck"].append(key)
                continue
        else:
            path = outdoor_line(_xy(a), _xy(b), area, params, through_barriers=True)
        if path is None:
            report.dropped["crosses_building"].append(key)
            continue
        if len(path) > 2:
            report.detoured.append(key)
        edges[key] = _edge(a, b, EdgeOrigin.TOUR, path)
        report.tour_links_kept += 1

    outdoor = [n for n in nodes if n.kind in (NodeKind.OUTDOOR, NodeKind.ENTRANCE)]
    if len(outdoor) >= 2:
        xy = np.array([[n.enu[0], n.enu[1]] for n in outdoor])
        for i, j in sorted(KDTree(xy).query_pairs(params.infer_radius_m)):
            a, b = outdoor[i], outdoor[j]
            key = "|".join(sorted((a.id, b.id)))
            if key in edges:
                continue
            path = (
                deck_line(a, b, decks, area, params, inferred=True)
                if a.id in decks or b.id in decks
                else inferred_line(_xy(a), _xy(b), area, params)
            )
            if path is None:
                continue
            edges[key] = _edge(a, b, EdgeOrigin.INFERRED, path)
            report.inferred_links += 1
            if len(path) > 2:
                report.detoured.append(key)

    for dropped in report.dropped.values():
        dropped.sort()
    report.detoured.sort()
    return sorted(edges.values(), key=lambda e: e.id), report


def blocked_edges(graph: Graph, footprints: BaseGeometry) -> list[str]:
    """Edges whose walking line cuts a building (must be empty to publish).

    Exempt: passages (walks through a building, never drawn) and links
    within one position (an indoor spot and its door). Every other line,
    doors at borrowed positions included, must keep clear of buildings.
    """
    obstacles = Obstacles.of(footprints)
    by_id = {n.id: n for n in graph.nodes}
    blocked: list[str] = []
    for edge in graph.edges:
        a, b = by_id[edge.source], by_id[edge.target]
        if edge.passage or position_of(a) == position_of(b):
            continue
        line = edge.path_enu or [_xy(a), _xy(b)]
        if not obstacles.clear(line):
            blocked.append(edge.id)
    return blocked


def _drawn_on_ground(
    edge: Edge, a: Node, b: Node, decks: Mapping[str, Deck]
) -> list[tuple[float, float]] | None:
    """The part of an edge's line on the ground, [] for one all up on a
    deck; None when its part up there leaves the deck's floor."""
    path = list(edge.path_enu or [_xy(a), _xy(b)])
    if a.id not in decks and b.id not in decks:
        return path
    on_floor, ground = _deck_ground(path, a, b, decks)
    return ground if on_floor else None


def mark_crossings(
    graph: Graph, area: WalkingArea, decks: Mapping[str, Deck] | None = None
) -> Graph:
    """Edges whose drawn line crosses a wall or fence, or seating or a hedge
    (one a spot stands in included): routes take them only when they must."""
    decks = decks or {}
    by_id = {n.id: n for n in graph.nodes}
    edges: list[Edge] = []
    for edge in graph.edges:
        a, b = by_id[edge.source], by_id[edge.target]
        crosses: EdgeCrossing | None = None
        if not edge.passage and position_of(a) != position_of(b):
            path = _drawn_on_ground(edge, a, b, decks)
            if path is None or (
                path and (not area.lenient.clear(path) or area.leaks(path))
            ):
                crosses = EdgeCrossing.BARRIER
            elif path and any(
                part.intersects(LineString(path))
                for part in area.soft_for(path[0], path[-1])
            ):
                crosses = EdgeCrossing.SOFT
        edges.append(edge.model_copy(update={"crosses": crosses}))
    return graph.model_copy(update={"edges": edges})


def crossings(
    graph: Graph, area: WalkingArea, decks: Mapping[str, Deck] | None = None
) -> tuple[list[str], list[str]]:
    """Drawn edges over a wall or the fence, and those (only) through soft
    obstacles or a stride from walls: ``(barrier, soft)``."""
    decks = decks or {}
    by_id = {n.id: n for n in graph.nodes}
    barrier: list[str] = []
    soft: list[str] = []
    for edge in graph.edges:
        a, b = by_id[edge.source], by_id[edge.target]
        if edge.passage or position_of(a) == position_of(b):
            continue
        line = _drawn_on_ground(edge, a, b, decks)
        if line is None or (
            line and (not area.lenient.clear(line) or area.leaks(line))
        ):
            barrier.append(edge.id)
        elif line and not area.preferred(line[0], line[-1]).clear(line):
            soft.append(edge.id)
    return barrier, soft


def bridge_islands(
    nodes: list[Node],
    edges: list[Edge],
    footprints: BaseGeometry,
    params: GraphParams = GraphParams(),  # noqa: B008 - frozen dataclass
    report: BuildReport | None = None,
    barriers: Barriers | None = None,
) -> list[Edge]:
    """Join islands of the measured network to the main one, walking outside.

    An SfM model no tour link joins to the rest (the T Blok garden) is
    reachable only through a building otherwise. Each island gets the
    shortest walk round buildings from one of its spots to the main network,
    tried over the nearest pairs within ``bridge_max_m``; none if no walk
    is reasonable (the outdoor link rules).
    """
    area = walking_area(footprints, barriers)
    up = deck_spots(barriers)
    walkers = {
        n.id: n
        for n in nodes
        if n.kind in (NodeKind.OUTDOOR, NodeKind.ENTRANCE) and n.id not in up
    }
    root = {n.id: n.id for n in nodes}

    def find(n: str) -> str:
        while root[n] != n:
            root[n] = root[root[n]]
            n = root[n]
        return n

    for edge in edges:
        a, b = sorted((find(edge.source), find(edge.target)))
        root[b] = a
    groups: dict[str, list[str]] = {}
    for n in sorted(root):
        groups.setdefault(find(n), []).append(n)
    ordered = sorted(groups.values(), key=lambda g: (-len(g), g[0]))
    if not ordered:
        return []
    main = set(ordered[0])
    bridges: list[Edge] = []
    for island in ordered[1:]:
        pairs = sorted(
            (math.dist(_xy(walkers[a]), _xy(walkers[b])), a, b)
            for a in island
            if a in walkers
            for b in sorted(main)
            if b in walkers
        )
        walks: list[tuple[float, str, str, list[tuple[float, float]]]] = []
        for straight, a, b in pairs[:24]:
            if straight > params.bridge_max_m:
                break
            line = outdoor_line(
                _xy(walkers[a]),
                _xy(walkers[b]),
                area,
                params,
                bends_ok=True,
                through_barriers=True,
            )
            if line is not None:
                walks.append((path_length(line), a, b, line))
        if not walks:
            continue
        # The shortest walk, and a few more to other parts of the network: a
        # single bridge makes every route from the island visit its far end,
        # turning back there when it heads elsewhere.
        walks.sort(key=lambda w: (w[0], w[1], w[2]))
        chosen: list[tuple[float, str, str, list[tuple[float, float]]]] = []
        for walk in walks:
            if len(chosen) == params.bridge_count:
                break
            if chosen and walk[0] > chosen[0][0] * params.bridge_spread_ratio:
                break
            if any(
                math.dist(_xy(walkers[walk[2]]), _xy(walkers[c[2]]))
                < params.bridge_spread_m
                for c in chosen
            ):
                continue
            chosen.append(walk)
        for _, a, b, line in chosen:
            bridge = _edge(walkers[a], walkers[b], EdgeOrigin.INFERRED, line)
            bridges.append(bridge)
            if report is not None:
                report.bridged.append(bridge.id)
        main |= set(island)
    return bridges


# A route turning back sharper than this at a spot draws a hook there.
HOOK_TURN_DEG = 120.0


def _heading(line: list[tuple[float, float]]) -> tuple[float, float] | None:
    dx, dy = line[-1][0] - line[-2][0], line[-1][1] - line[-2][1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 1e-6 else None


def shortcut_hooks(
    nodes: list[Node],
    edges: list[Edge],
    footprints: BaseGeometry,
    params: GraphParams = GraphParams(),  # noqa: B008 - frozen dataclass
    report: BuildReport | None = None,
    barriers: Barriers | None = None,
) -> list[Edge]:
    """Direct walks past the spots routes would hook round.

    A spot reached round a corner (a detour's last bend beyond it) sends a
    route through it back the way it came: p -> m -> q turns sharper than
    ``HOOK_TURN_DEG`` at m. Where p and q see each other past every
    obstacle (or round a corner or two), the walk between them joins them
    directly, shorter than the hook.
    """
    area = walking_area(footprints, barriers)
    up = deck_spots(barriers)
    by_id = {n.id: n for n in nodes}
    walked = {NodeKind.OUTDOOR, NodeKind.ENTRANCE}
    lines: dict[str, dict[str, list[tuple[float, float]]]] = {}
    for edge in edges:
        a, b = by_id[edge.source], by_id[edge.target]
        if edge.passage or a.kind not in walked or b.kind not in walked:
            continue
        # A walk on a raised deck is drawn up there: no ground shortcut for it.
        if a.id in up or b.id in up:
            continue
        line = list(edge.path_enu or [_xy(a), _xy(b)])
        lines.setdefault(a.id, {})[b.id] = line
        lines.setdefault(b.id, {})[a.id] = line[::-1]
    known = {e.id for e in edges}
    added: list[Edge] = []
    for m in sorted(lines):
        for p, q in itertools.combinations(sorted(lines[m]), 2):
            key = "|".join(sorted((p, q)))
            if key in known:
                continue
            into = _heading(lines[p][m])  # p -> m, arriving at m
            out = _heading(lines[m][q][::-1])  # q -> m, arriving at m
            if into is None or out is None:
                continue
            # Leaving m towards q is the reverse of arriving from q.
            cos = -(into[0] * out[0] + into[1] * out[1])
            if cos > math.cos(math.radians(HOOK_TURN_DEG)):
                continue
            via = path_length(lines[p][m]) + path_length(lines[m][q])
            a, b = _xy(by_id[p]), _xy(by_id[q])
            walk = None
            # A narrow lane may only take the lenient line (as tour links
            # do); never one over a wall or the fence.
            for tier in (area.preferred(a, b), area.snug(a, b), area.lenient):
                walk = walk_around(a, b, tier)
                if (
                    walk is not None
                    and path_length(walk) < via
                    and not area.leaks(walk)
                ):
                    break
                walk = None
            if (
                walk is None
                or len(walk) > 2 + params.corner_vertices
                or path_length(walk) >= via
            ):
                continue
            edge = _edge(by_id[p], by_id[q], EdgeOrigin.INFERRED, walk)
            added.append(edge)
            known.add(key)
            if report is not None:
                report.shortcuts.append(f"{key} past {m}")
    return added


def step_free_conflicts(graph: Graph) -> list[str]:
    """Step-free stretches that reach two known floors (must be empty).

    Without its stairs edges the graph falls apart into pieces; a piece with
    two different known storeys would let a "step-free" route change floor.
    """
    by_id = {n.id: n for n in graph.nodes}
    root = {n.id: n.id for n in graph.nodes}

    def find(n: str) -> str:
        while root[n] != n:
            root[n] = root[root[n]]
            n = root[n]
        return n

    for edge in graph.edges:
        if edge.kind is EdgeKind.STAIRS:
            continue
        a, b = sorted((find(edge.source), find(edge.target)))
        root[b] = a
    floors: dict[str, set[int]] = {}
    for node in graph.nodes:
        if node.level is not None:
            floors.setdefault(find(node.id), set()).add(node.level)
    return sorted(
        f"{by_id[r].label.tr} ({r}): floors {sorted(levels)}"
        for r, levels in floors.items()
        if len(levels) > 1
    )


def components(graph: Graph) -> list[list[str]]:
    adjacency: dict[str, set[str]] = {n.id: set() for n in graph.nodes}
    for edge in graph.edges:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)
    seen: set[str] = set()
    result: list[list[str]] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack, comp = [start], []
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            comp.append(node)
            stack.extend(adjacency[node] - seen)
        result.append(sorted(comp))
    result.sort(key=lambda c: (-len(c), c[0]))
    return result


def build_graph(
    posed: Mapping[str, Mapping[str, Any]],
    scenes: Mapping[str, Mapping[str, Any]],
    footprints: BaseGeometry,
    run_id: str,
    params: GraphParams = GraphParams(),  # noqa: B008 - frozen dataclass
    barriers: Barriers | None = None,
) -> tuple[Graph, BuildReport]:
    report = BuildReport()
    area = walking_area(footprints, barriers)
    decks = deck_spots(barriers)
    nodes = snap_nodes(make_nodes(posed, scenes), area.lenient, report)
    tour_links = [(a, b) for a in posed for b in scenes[a]["links"]]
    edges, report = make_edges(nodes, tour_links, footprints, params, report, barriers)
    edges = [
        *edges,
        *bridge_islands(nodes, edges, footprints, params, report, barriers),
    ]
    edges = sorted(
        [*edges, *shortcut_hooks(nodes, edges, footprints, params, report, barriers)],
        key=lambda e: e.id,
    )

    def walkable(a: Node, b: Node) -> list[tuple[float, float]] | None:
        """Two doors at different positions: a walk outside, as tour links."""
        if math.dist(a.enu, b.enu) > params.max_link_m:
            return None
        if a.id in decks or b.id in decks:
            return deck_line(a, b, decks, area, params)
        return outdoor_line(_xy(a), _xy(b), area, params, through_barriers=True)

    if params.indoor:
        nodes, indoor_edges, report.indoor = attach_indoor(nodes, scenes, walkable)
        reached = {e.id for e in indoor_edges}
        report.dropped["unposed"] = [
            k for k in report.dropped["unposed"] if k not in reached
        ]
        edges = sorted([*edges, *indoor_edges], key=lambda e: e.id)
    meta = GraphMeta(
        generated_at=datetime.now(UTC),
        run_id=run_id,
        origin_lat=CAMPUS_ORIGIN_LAT,
        origin_lng=CAMPUS_ORIGIN_LNG,
    )
    graph = mark_crossings(Graph(meta=meta, nodes=nodes, edges=edges), area, decks)
    report.barrier_fallback, report.soft_fallback = crossings(graph, area, decks)
    return graph, report


def summarise(graph: Graph, report: BuildReport) -> dict[str, Any]:
    comps = components(graph)
    # Edge statistics of the measured network; indoor lengths are estimates.
    lengths = [
        e.length_m for e in graph.edges if e.length_source is not LengthSource.ESTIMATE
    ]
    indoor_nodes = [n for n in graph.nodes if n.approximate]
    indoor_edges = [e for e in graph.edges if e.length_source is LengthSource.ESTIMATE]
    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "tour_links_kept": report.tour_links_kept,
        "inferred_links": report.inferred_links,
        "dropped": {k: len(v) for k, v in report.dropped.items()},
        "snapped_nodes": len(report.snapped),
        "unsnapped_nodes": len(report.unsnapped),
        "soft_fallback_edges": len(report.soft_fallback),
        "barrier_fallback_edges": len(report.barrier_fallback),
        "detoured_edges": len(report.detoured),
        "components": [len(c) for c in comps],
        "median_edge_m": round(float(np.median(lengths)), 2) if lengths else None,
        "max_edge_m": round(max(lengths), 2) if lengths else None,
        "total_length_m": round(math.fsum(lengths), 1),
        "indoor": {
            "nodes": len(indoor_nodes),
            "entrances": sum(n.kind is NodeKind.ENTRANCE for n in indoor_nodes),
            "edges": len(indoor_edges),
            "stairs": sum(e.kind is EdgeKind.STAIRS for e in indoor_edges),
            "with_floor": sum(n.floor is not None for n in indoor_nodes),
            "with_building": sum(n.building is not None for n in indoor_nodes),
            "floors": report.indoor.floors,
            "unreachable": len(report.indoor.unreachable),
            "passages": sum(e.passage for e in graph.edges),
            "menu_jumps": len(report.indoor.menu_jumps),
            "door_walks": len(report.indoor.door_walks),
        },
        "bridges": len(report.bridged),
        "step_free_conflicts": len(step_free_conflicts(graph)),
    }
