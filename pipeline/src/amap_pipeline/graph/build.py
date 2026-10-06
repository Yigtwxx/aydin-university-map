"""Build the metric walking graph from georeferenced panoramas.

Nodes are panoramas with a georeferenced SfM pose. Edges come from two sources:

- **tour** links of the 360 tour whose both ends are posed, kept only if they
  are physically walkable: no longer than ``max_link_m`` (longer ones are
  teleports to distant buildings) and not crossing a building footprint
  (links that end at an entrance or indoor pano may pass a doorway);
- **inferred** links between outdoor panoramas closer than ``infer_radius_m``
  with a clear line of sight, which densifies the sparse tour network.

Lengths are 3D distances between camera centres (local metres).
"""

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import shapely
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

_BLOCK_RE = re.compile(r"\b([A-Z](?:-[A-Z])?) Blok\b")
DOORWAY_KINDS = frozenset({NodeKind.ENTRANCE, NodeKind.INDOOR})


@dataclass(frozen=True, slots=True)
class GraphParams:
    max_link_m: float = 60.0
    infer_radius_m: float = 12.0
    footprint_shrink_m: float = 0.75


@dataclass(slots=True)
class BuildReport:
    tour_links_kept: int = 0
    inferred_links: int = 0
    dropped: dict[str, list[str]] = field(
        default_factory=lambda: {"teleport": [], "crosses_building": [], "unposed": []}
    )


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


def _edge(a: Node, b: Node, origin: EdgeOrigin) -> Edge:
    first, second = sorted((a, b), key=lambda n: n.id)
    length = float(np.linalg.norm(np.subtract(first.enu, second.enu)))
    return Edge(
        id=f"{first.id}|{second.id}",
        source=first.id,
        target=second.id,
        kind=_edge_kind(first, second),
        origin=origin,
        length_m=max(length, 0.01),
        cost_s=max(length, 0.01) / WALKING_SPEED_MPS,
        length_source=LengthSource.SFM,
    )


def _crosses(blockers: BaseGeometry, a: Node, b: Node) -> bool:
    line = shapely.linestrings([[a.enu[0], a.enu[1]], [b.enu[0], b.enu[1]]])
    return bool(shapely.intersects(blockers, line))


def make_edges(
    nodes: list[Node],
    tour_links: Iterable[tuple[str, str]],
    footprints: BaseGeometry,
    params: GraphParams = GraphParams(),  # noqa: B008 - frozen dataclass
) -> tuple[list[Edge], BuildReport]:
    by_id = {n.id: n for n in nodes}
    blockers = footprints.buffer(-params.footprint_shrink_m)
    shapely.prepare(blockers)
    report = BuildReport()
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
        edge = _edge(a, b, EdgeOrigin.TOUR)
        if edge.length_m > params.max_link_m:
            report.dropped["teleport"].append(key)
            continue
        doorway = a.kind in DOORWAY_KINDS or b.kind in DOORWAY_KINDS
        if not doorway and _crosses(blockers, a, b):
            report.dropped["crosses_building"].append(key)
            continue
        edges[key] = edge
        report.tour_links_kept += 1

    outdoor = [n for n in nodes if n.kind in (NodeKind.OUTDOOR, NodeKind.ENTRANCE)]
    if len(outdoor) >= 2:
        xy = np.array([[n.enu[0], n.enu[1]] for n in outdoor])
        for i, j in sorted(KDTree(xy).query_pairs(params.infer_radius_m)):
            a, b = outdoor[i], outdoor[j]
            key = "|".join(sorted((a.id, b.id)))
            if key in edges or _crosses(blockers, a, b):
                continue
            edges[key] = _edge(a, b, EdgeOrigin.INFERRED)
            report.inferred_links += 1

    for dropped in report.dropped.values():
        dropped.sort()
    return sorted(edges.values(), key=lambda e: e.id), report


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
    nodes = make_nodes(posed, scenes)
    tour_links = [(a, b) for a in posed for b in scenes[a]["links"]]
    edges, report = make_edges(nodes, tour_links, footprints, params)
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
        "components": [len(c) for c in comps],
        "median_edge_m": round(float(np.median(lengths)), 2) if lengths else None,
        "max_edge_m": round(max(lengths), 2) if lengths else None,
        "total_length_m": round(math.fsum(lengths), 1),
    }
