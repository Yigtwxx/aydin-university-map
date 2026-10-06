"""Building heights from the georeferenced SfM/MVS point cloud.

Per OSM footprint (local ENU metres, z up):

- ground = ``ground_quantile`` (p10) of the points 3-10 m outside the footprint,
  leaving out points that fall inside any other footprint (neighbouring
  facades are not ground) and, when the cloud has normals, points on
  non-horizontal surfaces (facades, trees: |n_z| below ``ground_min_nz``);
- roof = ``roof_quantile`` (p95) of the points inside the footprint shrunk by
  1 m (so facade points measured on the outline do not count as roof),
  counting only points more than ``roof_above_ground_m`` above the ground
  (glass reflections land behind and below the facade);
- ground candidates must lie within ``max_ground_offset_m`` of the model's
  ground (z = 0 under the cameras): mirror images in glass sit far below it;
- height = roof - ground, accepted only with enough points inside and a
  plausible value (3-80 m by default).

Street-level panoramas rarely see a flat roof, so "roof" is mostly the top of
the visible facade or parapet; the acceptance rules keep only footprints the
cloud actually covers.
"""

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class HeightParams:
    ground_ring_m: tuple[float, float] = (3.0, 10.0)
    ground_quantile: float = 0.10
    roof_quantile: float = 0.95
    shrink_m: float = 1.0
    min_inside: int = 30
    min_ground: int = 10
    ground_min_nz: float = 0.8  # with normals: ground points face up (or down)
    height_range_m: tuple[float, float] = (3.0, 80.0)
    roof_above_ground_m: float = 1.0
    max_ground_offset_m: float = 4.0


@dataclass(frozen=True, slots=True)
class SfmHeight:
    height_m: float
    points: int  # points inside the shrunk footprint
    ground_m: float
    roof_m: float
    ground_points: int

    def as_json(self) -> dict[str, float | int]:
        return {
            "height_m": round(self.height_m, 2),
            "points": self.points,
            "ground_m": round(self.ground_m, 2),
        }


class PointIndex:
    """Points sorted by x for fast axis-aligned box queries.

    Rows are (x, y, z) or (x, y, z, |n_z|) when normals are known.
    """

    def __init__(self, points: FloatArray, normals: FloatArray | None = None) -> None:
        rows = points[:, :3]
        if normals is not None:
            rows = np.column_stack([rows, np.abs(normals[:, 2])])
        order = np.argsort(rows[:, 0], kind="stable")
        self.points = rows[order]
        self.has_normals = normals is not None

    def box(self, x0: float, y0: float, x1: float, y1: float) -> FloatArray:
        xs = self.points[:, 0]
        lo, hi = np.searchsorted(xs, [x0, x1], side="left")
        sub = self.points[lo:hi]
        return sub[(sub[:, 1] >= y0) & (sub[:, 1] <= y1)]


def _inside(geometry: BaseGeometry, pts: FloatArray) -> NDArray[np.bool_]:
    if geometry.is_empty or len(pts) == 0:
        return np.zeros(len(pts), dtype=bool)
    return np.asarray(shapely.contains_xy(geometry, pts[:, 0], pts[:, 1]))


def footprint_height(
    index: PointIndex,
    outline: Polygon,
    others: BaseGeometry | None,
    params: HeightParams = HeightParams(),  # noqa: B008 - frozen, immutable
) -> SfmHeight | None:
    """Height of one footprint, or None when the cloud does not support it."""
    near, far = params.ground_ring_m
    x0, y0, x1, y1 = outline.bounds
    pts = index.box(x0 - far, y0 - far, x1 + far, y1 + far)
    if len(pts) == 0:
        return None
    roof_area = outline.buffer(-params.shrink_m)
    inside = pts[_inside(roof_area, pts)]
    if len(inside) < params.min_inside:
        return None
    ring = outline.buffer(far).difference(outline.buffer(near))
    if others is not None and not others.is_empty:
        ring = ring.difference(others)
    ground_pts = pts[_inside(ring, pts)]
    if index.has_normals:
        ground_pts = ground_pts[ground_pts[:, 3] >= params.ground_min_nz]
    # Mirror images in glass and water land far below the real ground.
    ground_pts = ground_pts[np.abs(ground_pts[:, 2]) <= params.max_ground_offset_m]
    if len(ground_pts) < params.min_ground:
        return None
    ground = float(np.quantile(ground_pts[:, 2], params.ground_quantile))
    inside = inside[inside[:, 2] > ground + params.roof_above_ground_m]
    if len(inside) < params.min_inside:
        return None
    roof = float(np.quantile(inside[:, 2], params.roof_quantile))
    height = roof - ground
    lo, hi = params.height_range_m
    if not lo <= height <= hi:
        return None
    return SfmHeight(height, len(inside), ground, roof, len(ground_pts))


def building_heights(
    points: FloatArray,
    footprints: Iterable[tuple[str, Polygon]],
    params: HeightParams = HeightParams(),  # noqa: B008 - frozen, immutable
    normals: FloatArray | None = None,
) -> dict[str, SfmHeight]:
    """Accepted heights per footprint id (points/normals: (N, 3) ENU)."""
    items = [(fid, poly) for fid, poly in footprints if poly.is_valid]
    if len(points) == 0 or not items:
        return {}
    index = PointIndex(points, normals)
    polys = [poly for _, poly in items]
    tree = shapely.STRtree(polys)
    lo = points[:, :2].min(axis=0) - params.ground_ring_m[1]
    hi = points[:, :2].max(axis=0) + params.ground_ring_m[1]
    out: dict[str, SfmHeight] = {}
    for i, (fid, poly) in enumerate(items):
        x0, y0, x1, y1 = poly.bounds
        if x1 < lo[0] or x0 > hi[0] or y1 < lo[1] or y0 > hi[1]:
            continue
        grown = poly.buffer(params.ground_ring_m[1])
        neighbours = [polys[j] for j in tree.query(grown) if j != i]
        others = shapely.union_all(neighbours) if neighbours else None
        found = footprint_height(index, poly, others, params)
        if found is not None:
            out[fid] = found
    return out


def apply_sfm_heights(
    buildings: Sequence[MutableMapping[str, Any]],
    heights: Mapping[str, Mapping[str, Any]],
) -> int:
    """Raise ``height_m`` to the measured height (``height_source = "sfm"``).

    Ground-level panoramas rarely see the top floors and the roof edge, so a
    measured height is a lower bound: it only replaces lower estimates.
    """
    applied = 0
    for building in buildings:
        found = heights.get(str(building.get("id")))
        if found is None:
            continue
        measured = round(float(found["height_m"]), 2)
        if measured <= float(building.get("height_m", 0.0)):
            continue
        building["height_m"] = measured
        building["height_source"] = "sfm"
        applied += 1
    return applied
