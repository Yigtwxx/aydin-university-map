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

Lengths are 3D distances between camera centres (local metres), measured
along the detour when there is one.
"""

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import numpy as np
from scipy.spatial import KDTree
from shapely.geometry.base import BaseGeometry

from amap_contracts import CAMPUS_ORIGIN_LAT, CAMPUS_ORIGIN_LNG
from amap_contracts.graph import (
    WALKING_SPEED_MPS,
    Edge,
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
from amap_pipeline.graph.clearance import (
    Obstacles,
    path_length,
    snap_point,
    walk_around,
)

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


@dataclass(slots=True)
class BuildReport:
    tour_links_kept: int = 0
    inferred_links: int = 0
    dropped: dict[str, list[str]] = field(
        default_factory=lambda: {"teleport": [], "crosses_building": [], "unposed": []}
    )
    snapped: dict[str, float] = field(default_factory=dict)  # node -> metres moved
    detoured: list[str] = field(default_factory=list)


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
                pose_source=PoseSource.SFM,
                label=LocalizedText(tr=meta["label"]["tr"], en=meta["label"]["en"]),
                area=LocalizedText(tr=meta["area"]["tr"], en=meta["area"]["en"]),
                building=building_of(meta["label"]["tr"]),
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


def make_edges(
    nodes: list[Node],
    tour_links: Iterable[tuple[str, str]],
    footprints: BaseGeometry,
    params: GraphParams = GraphParams(),  # noqa: B008 - frozen dataclass
    report: BuildReport | None = None,
) -> tuple[list[Edge], BuildReport]:
    by_id = {n.id: n for n in nodes}
    obstacles = Obstacles.of(footprints)
    report = report if report is not None else BuildReport()
    edges: dict[str, Edge] = {}

    seen: set[str] = set()
    for a_id, b_id in tour_links:
        key = "|".join(sorted((a_id, b_id)))
        if key in seen:  # links are listed from both ends
            continue
        seen.add(key)
        if a_id not in by_id or b_id not in by_id:
            report.dropped["unposed"].append(key)
            continue
        a, b = by_id[a_id], by_id[b_id]
        straight = math.dist(_xy(a), _xy(b))
        if _edge(a, b, EdgeOrigin.TOUR).length_m > params.max_link_m:
            report.dropped["teleport"].append(key)
            continue
        if NodeKind.INDOOR in (a.kind, b.kind):
            # Indoor panoramas are inside by definition (indoor routing).
            edges[key] = _edge(a, b, EdgeOrigin.TOUR)
            report.tour_links_kept += 1
            continue
        path = walk_around(_xy(a), _xy(b), obstacles)
        allowed = max(
            straight * params.max_detour_ratio, straight + params.max_detour_extra_m
        )
        too_long = len(path or []) > 2 and straight > params.max_detour_link_m
        if path is None or too_long or path_length(path) > allowed:
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
            if not obstacles.crosses(_xy(a), _xy(b)):
                edges[key] = _edge(a, b, EdgeOrigin.INFERRED)
                report.inferred_links += 1
                continue
            # Round the corner of a block instead of visiting a door to turn.
            path = walk_around(_xy(a), _xy(b), obstacles)
            straight = math.dist(_xy(a), _xy(b))
            if (
                path is not None
                and len(path) <= 2 + params.corner_vertices
                and path_length(path) <= straight * params.corner_ratio
            ):
                edges[key] = _edge(a, b, EdgeOrigin.INFERRED, path)
                report.inferred_links += 1
                report.detoured.append(key)

    for dropped in report.dropped.values():
        dropped.sort()
    report.detoured.sort()
    return sorted(edges.values(), key=lambda e: e.id), report


def blocked_edges(graph: Graph, footprints: BaseGeometry) -> list[str]:
    """Edges whose walking line cuts a building (must be empty to publish)."""
    obstacles = Obstacles.of(footprints)
    by_id = {n.id: n for n in graph.nodes}
    blocked: list[str] = []
    for edge in graph.edges:
        a, b = by_id[edge.source], by_id[edge.target]
        if NodeKind.INDOOR in (a.kind, b.kind):
            continue
        line = edge.path_enu or [_xy(a), _xy(b)]
        if any(obstacles.crosses(p, q) for p, q in pairwise(line)):
            blocked.append(edge.id)
    return blocked


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
) -> tuple[Graph, BuildReport]:
    report = BuildReport()
    nodes = snap_nodes(make_nodes(posed, scenes), Obstacles.of(footprints), report)
    tour_links = [(a, b) for a in posed for b in scenes[a]["links"]]
    edges, report = make_edges(nodes, tour_links, footprints, params, report)
    meta = GraphMeta(
        generated_at=datetime.now(UTC),
        run_id=run_id,
        origin_lat=CAMPUS_ORIGIN_LAT,
        origin_lng=CAMPUS_ORIGIN_LNG,
    )
    return Graph(meta=meta, nodes=nodes, edges=edges), report


def summarise(graph: Graph, report: BuildReport) -> dict[str, Any]:
    comps = components(graph)
    lengths = [e.length_m for e in graph.edges]
    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "tour_links_kept": report.tour_links_kept,
        "inferred_links": report.inferred_links,
        "dropped": {k: len(v) for k, v in report.dropped.items()},
        "snapped_nodes": len(report.snapped),
        "detoured_edges": len(report.detoured),
        "components": [len(c) for c in comps],
        "median_edge_m": round(float(np.median(lengths)), 2) if lengths else None,
        "max_edge_m": round(max(lengths), 2) if lengths else None,
        "total_length_m": round(math.fsum(lengths), 1),
    }
