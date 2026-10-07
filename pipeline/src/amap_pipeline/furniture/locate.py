"""From detections (angles in panoramas) to furniture candidates on the map.

Two ways to place a detection:

* monoplot: the ray to the box's bottom meets level ground at
  ``tripod / tan(atv)`` metres. Needs the camera height, sensitive to slopes.
* triangulation: the same object seen from two or more panoramas sits where
  the bearings meet. Needs no height at all.

Detections are clustered per kind on their monoplot positions; a cluster seen
from 2+ panoramas is triangulated. Comparing both on the same objects measures
the tripod height: ``h = d_triangulated * tan(atv)``.
"""

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import KDTree

from amap_pipeline.geo.angles import wrap180
from amap_pipeline.look.camera import Pose, ath_to_bearing, ground_point

# Lowest score worth a look, per kind (the detector is generous with chairs).
MIN_SCORE: dict[str, float] = {
    "bench": 0.25,
    "planter": 0.25,
    "bollard": 0.28,
    "bin": 0.3,
    "lamp": 0.3,
    "stairs": 0.2,
    "railing": 0.28,
    "table": 0.3,
    "chair": 0.33,
    "umbrella": 0.3,
    "bike_rack": 0.25,
}
# Cluster radius per kind, metres.
EPS_M: dict[str, float] = {
    "bench": 1.5,
    "planter": 1.0,
    "bollard": 0.7,
    "bin": 0.8,
    "lamp": 1.0,
    "stairs": 3.0,
    "railing": 2.5,
    "table": 1.0,
    "chair": 0.9,
    "umbrella": 1.5,
    "bike_rack": 1.5,
}
MAX_RANGE_M = 16.0
MIN_ATV_DEG = 4.0  # flatter than this, the ground hit is too far to trust


@dataclass(frozen=True, slots=True)
class Placed:
    scene: str
    kind: str
    score: float
    x: float
    y: float
    range_m: float
    bearing_deg: float
    atv_deg: float
    width_m: float


@dataclass(slots=True)
class Candidate:
    kind: str
    x: float
    y: float
    method: str  # triangulated | monoplot
    scenes: list[str]
    score: float  # best detector score
    spread_m: float  # how far the members scatter around the estimate
    width_m: float
    members: list[Placed] = field(default_factory=list[Placed])


def place(
    detections: Sequence[Mapping[str, object]],
    poses: Mapping[str, Pose],
    *,
    max_range_m: float = MAX_RANGE_M,
) -> list[Placed]:
    out: list[Placed] = []
    for d in detections:
        kind = str(d["kind"])
        score = float(d["score"])  # type: ignore[arg-type]
        pose = poses.get(str(d["scene"]))
        if pose is None or score < MIN_SCORE.get(kind, 0.3):
            continue
        ath = float(d["ath_deg"])  # type: ignore[arg-type]
        atv = float(d["atv_bottom_deg"])  # type: ignore[arg-type]
        if atv < MIN_ATV_DEG:
            continue
        hit = ground_point(pose, ath, atv)
        if hit is None:
            continue
        rng = math.hypot(hit[0] - pose.x, hit[1] - pose.y)
        if rng > max_range_m:
            continue
        span = abs(
            wrap180(float(d["ath_right_deg"]) - float(d["ath_left_deg"]))  # type: ignore[arg-type]
        )
        out.append(
            Placed(
                scene=pose.scene,
                kind=kind,
                score=score,
                x=hit[0],
                y=hit[1],
                range_m=rng,
                bearing_deg=ath_to_bearing(pose, ath),
                atv_deg=atv,
                width_m=2.0 * rng * math.tan(math.radians(span / 2.0)),
            )
        )
    return out


def _ray_meet(
    a: Placed, b: Placed, poses: Mapping[str, Pose]
) -> tuple[float, float] | None:
    """Distances along each ray to where two bearings meet (forward only)."""
    pa, pb = poses[a.scene], poses[b.scene]
    ra, rb = math.radians(a.bearing_deg), math.radians(b.bearing_deg)
    da = np.array([math.sin(ra), math.cos(ra)])
    db = np.array([math.sin(rb), math.cos(rb)])
    m = np.column_stack([da, -db])
    if abs(np.linalg.det(m)) < 1e-6:
        return None
    t = np.linalg.solve(m, np.array([pb.x - pa.x, pb.y - pa.y]))
    if t[0] <= 0 or t[1] <= 0:
        return None
    return float(t[0]), float(t[1])


def _linked(
    a: Placed, b: Placed, poses: Mapping[str, Pose], min_angle_deg: float = 10.0
) -> bool:
    """Same object? Same panorama: same bearing and range. Two panoramas: their
    rays cross at a usable angle, at distances each ray's ground hit agrees
    with up to a camera-height error of about 50 %."""
    if a.scene == b.scene:
        return abs(wrap180(a.bearing_deg - b.bearing_deg)) < 2.0 and abs(
            a.range_m - b.range_m
        ) < 0.25 * max(a.range_m, b.range_m)
    crossing = abs(wrap180(a.bearing_deg - b.bearing_deg))
    if min(crossing, 180.0 - crossing) < min_angle_deg:
        return False
    meet = _ray_meet(a, b, poses)
    if meet is None:
        return False
    return all(
        0.6 <= t / r <= 1.6 for t, r in ((meet[0], a.range_m), (meet[1], b.range_m))
    )


def _components(
    items: Sequence[Placed], poses: Mapping[str, Pose], search_m: float
) -> list[list[int]]:
    """Group detections of one kind that are the same object."""
    if not items:
        return []
    points = np.array([[p.x, p.y] for p in items])
    tree = KDTree(points)
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in tree.query_pairs(search_m):
        if _linked(items[a], items[b], poses):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def triangulate(
    members: Sequence[Placed], poses: Mapping[str, Pose], min_angle_deg: float = 15.0
) -> tuple[float, float] | None:
    """Bearing-only meeting point of one ray per panorama (the nearest)."""
    best: dict[str, Placed] = {}
    for m in members:
        if m.scene not in best or m.range_m < best[m.scene].range_m:
            best[m.scene] = m
    rays = list(best.values())
    if len(rays) < 2:
        return None
    widest = max(
        min(
            abs(wrap180(a.bearing_deg - b.bearing_deg)),
            180 - abs(wrap180(a.bearing_deg - b.bearing_deg)),
        )
        for i, a in enumerate(rays)
        for b in rays[i + 1 :]
    )
    if widest < min_angle_deg:
        return None
    normal = np.zeros((2, 2))
    rhs = np.zeros(2)
    for r in rays:
        p = poses[r.scene]
        rad = math.radians(r.bearing_deg)
        d = np.array([math.sin(rad), math.cos(rad)])
        proj = np.eye(2) - np.outer(d, d)
        normal += proj
        rhs += proj @ np.array([p.x, p.y])
    x, y = np.linalg.solve(normal, rhs)
    return float(x), float(y)


def cluster(
    placed: Sequence[Placed],
    poses: Mapping[str, Pose],
    *,
    single_view_score: float = 0.45,
    single_view_range_m: float = 8.0,
) -> list[Candidate]:
    """Candidates: seen from 2+ panoramas, or once but clearly and close."""
    out: list[Candidate] = []
    kinds = sorted({p.kind for p in placed})
    for kind in kinds:
        items = [p for p in placed if p.kind == kind]
        # Monoplot positions only shortlist pairs (generously: the camera
        # height may be off); the rays decide.
        search = max(6.0, 3.0 * EPS_M.get(kind, 1.0))
        for idx in _components(items, poses, search):
            members = [items[i] for i in idx]
            scenes = sorted({m.scene for m in members})
            best = max(m.score for m in members)
            tri = triangulate(members, poses) if len(scenes) >= 2 else None
            if tri is None:
                near = min(members, key=lambda m: m.range_m)
                if len(scenes) < 2 and (
                    best < single_view_score or near.range_m > single_view_range_m
                ):
                    continue
                weights = np.array([1.0 / max(m.range_m, 1.0) ** 2 for m in members])
                x = float(np.average([m.x for m in members], weights=weights))
                y = float(np.average([m.y for m in members], weights=weights))
                method = "monoplot"
            else:
                x, y = tri
                method = "triangulated"
            spread = float(np.median([math.hypot(m.x - x, m.y - y) for m in members]))
            out.append(
                Candidate(
                    kind=kind,
                    x=round(x, 2),
                    y=round(y, 2),
                    method=method,
                    scenes=scenes,
                    score=round(best, 3),
                    spread_m=round(spread, 2),
                    width_m=round(statistics.median(m.width_m for m in members), 2),
                    members=members,
                )
            )
    return out


def tripod_height(
    candidates: Sequence[Candidate], poses: Mapping[str, Pose]
) -> float | None:
    """Camera height implied by triangulated objects: d_tri * tan(atv), median."""
    heights: list[float] = []
    for c in candidates:
        if c.method != "triangulated":
            continue
        for m in c.members:
            p = poses[m.scene]
            d = math.hypot(c.x - p.x, c.y - p.y)
            if 2.0 < d < 12.0:
                heights.append(d * math.tan(math.radians(m.atv_deg)))
    return round(statistics.median(heights), 3) if len(heights) >= 5 else None
