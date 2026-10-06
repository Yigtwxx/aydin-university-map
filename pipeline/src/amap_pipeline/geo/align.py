"""Georeference an SfM model to OpenStreetMap building footprints.

The tour has no usable compass heading and only coarse coordinates, so the
model -> map transform is solved from geometry alone:

1. Gravity: rotate the model so the rig "down" axis points to -z (panos are
   levelled to < 1 deg). What remains is a 2D similarity (yaw, scale, shift).
2. Wall points: reconstructed points 0.5-3 m above the local ground (camera
   height minus the tripod height) are mostly facades; seen from above they
   trace building outlines.
3. Global search: for every yaw/scale candidate the best shift is found at once
   by FFT cross-correlation of the wall-point raster with a blurred outline
   raster. Candidates are ranked by score with a penalty for cameras that would
   stand inside a building.
4. Refinement: trimmed 2D ICP with scale on the best candidates.

All map coordinates are local metres (x east, y north) from ``geo.osm``.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import shapely
from numpy.typing import NDArray
from scipy.ndimage import distance_transform_edt
from scipy.signal import fftconvolve
from scipy.spatial import KDTree
from shapely import contains_xy
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from amap_pipeline.recon.evaluate import TRIPOD_HEIGHT_M, PanoPose, horizontal_basis

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Similarity2D:
    """map_xy = scale * R(yaw) @ model_xy + shift (yaw counter-clockwise, rad)."""

    yaw: float
    scale: float
    shift: tuple[float, float]

    def apply(self, xy: FloatArray) -> FloatArray:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        rot = np.array([[c, -s], [s, c]])
        return self.scale * xy @ rot.T + np.asarray(self.shift)


@dataclass(frozen=True, slots=True)
class LevelledModel:
    """Model expressed in a gravity-aligned frame (z up), still in model units."""

    basis: FloatArray  # 3x3, rows e1, e2, up: levelled = basis @ model
    cameras: dict[str, FloatArray]  # scene -> levelled camera centre
    points: FloatArray  # (N, 3) levelled points

    def camera_xy(self) -> FloatArray:
        return np.array([c[:2] for c in self.cameras.values()])


def level(
    poses: Sequence[PanoPose], points: FloatArray, down: FloatArray
) -> LevelledModel:
    e1, e2 = horizontal_basis(down)
    basis = np.stack([e1, e2, -down])
    return LevelledModel(
        basis=basis,
        cameras={p.scene: basis @ p.center for p in poses},
        points=points @ basis.T,
    )


def wall_points(
    model: LevelledModel,
    metres_per_unit: float,
    band_m: tuple[float, float] = (0.5, 3.0),
    max_range_m: float = 40.0,
) -> FloatArray:
    """XY (model units) of points in a height band above each nearby camera's ground."""
    cams = np.array(list(model.cameras.values()))
    tree = KDTree(cams[:, :2])
    dist, idx = tree.query(model.points[:, :2])
    ground = cams[idx, 2] - TRIPOD_HEIGHT_M / metres_per_unit
    height_m = (model.points[:, 2] - ground) * metres_per_unit
    keep = (
        (height_m > band_m[0])
        & (height_m < band_m[1])
        & (dist * metres_per_unit < max_range_m)
    )
    return model.points[keep, :2]


@dataclass(frozen=True, slots=True)
class Raster:
    origin: tuple[float, float]  # map xy of cell (0, 0) centre
    cell: float
    data: FloatArray

    def index(self, xy: FloatArray) -> NDArray[np.int64]:
        ij = np.floor((xy - np.asarray(self.origin)) / self.cell + 0.5).astype(np.int64)
        return ij[:, ::-1]  # (row = y, col = x)


def outline_score_raster(
    outline_xy: FloatArray,
    extent: tuple[float, float, float, float],
    cell: float,
    sigma_m: float = 1.5,
) -> Raster:
    """exp(-d^2 / 2 sigma^2) of the distance to the nearest outline sample."""
    xmin, ymin, xmax, ymax = extent
    cols = math.ceil((xmax - xmin) / cell) + 1
    rows = math.ceil((ymax - ymin) / cell) + 1
    occupied = np.zeros((rows, cols), dtype=bool)
    raster = Raster((xmin, ymin), cell, np.zeros((rows, cols)))
    ij = raster.index(outline_xy)
    ok = (ij[:, 0] >= 0) & (ij[:, 0] < rows) & (ij[:, 1] >= 0) & (ij[:, 1] < cols)
    occupied[ij[ok, 0], ij[ok, 1]] = True
    dist = np.asarray(distance_transform_edt(~occupied), dtype=np.float64) * cell
    return Raster((xmin, ymin), cell, np.exp(-(dist**2) / (2 * sigma_m**2)))


ANCHOR_SIGMA_M = 10.0


@dataclass(frozen=True, slots=True)
class Anchor:
    """A camera that must stand next to a named building (e.g. "A Blok Girişi")."""

    camera: int  # index into the cameras array passed to ``search``
    target: BaseGeometry  # that building's footprint


@dataclass(frozen=True, slots=True)
class Candidate:
    transform: Similarity2D  # raw model xy -> map xy
    score: float  # mean outline score of the wall points
    cameras_inside: float = 0.0  # fraction of cameras inside a footprint
    links_crossing: float = 0.0  # fraction of walking links crossing a footprint
    anchor_rms_m: float | None = None  # entrance-to-building distance (RMS)

    @property
    def rank_value(self) -> float:
        value = self.score * (1.0 - self.cameras_inside) ** 2
        value *= (1.0 - self.links_crossing) ** 2
        if self.anchor_rms_m is not None:
            value *= math.exp(-(self.anchor_rms_m**2) / (2 * ANCHOR_SIGMA_M**2))
        return value


def _point_raster(xy: FloatArray, cell: float) -> tuple[FloatArray, FloatArray]:
    """Counts raster of ``xy`` and the map xy of its (0, 0) cell centre."""
    lo = xy.min(axis=0)
    ij = np.floor((xy - lo) / cell + 0.5).astype(np.int64)
    shape = ij.max(axis=0) + 1
    grid = np.zeros((int(shape[1]), int(shape[0])))
    np.add.at(grid, (ij[:, 1], ij[:, 0]), 1.0)
    return grid, lo


def _top_peaks(corr: FloatArray, n: int, min_sep: float) -> list[tuple[int, int]]:
    """Up to ``n`` best cells of ``corr`` at least ``min_sep`` cells apart."""
    flat = corr.ravel()
    k = min(flat.size, max(n * 64, 1))
    best = np.argpartition(-flat, k - 1)[:k]
    best = best[np.argsort(-flat[best])]
    peaks: list[tuple[int, int]] = []
    for i in best:
        if not np.isfinite(flat[i]):
            break
        r, c = divmod(int(i), corr.shape[1])
        if all((r - pr) ** 2 + (c - pc) ** 2 >= min_sep**2 for pr, pc in peaks):
            peaks.append((r, c))
            if len(peaks) == n:
                break
    return peaks


def constrain(
    cand: Candidate,
    cameras: FloatArray,
    footprints: BaseGeometry,
    shrunk: BaseGeometry,
    anchors: Sequence[Anchor],
    links: Sequence[tuple[int, int]],
    with_links: bool = True,
) -> Candidate:
    """Attach physical-plausibility measures to a candidate."""
    cams = cand.transform.apply(cameras)
    inside = float(np.mean(contains_xy(footprints, cams[:, 0], cams[:, 1])))
    anchor_rms: float | None = None
    if anchors:
        pts = shapely.points(cams[[a.camera for a in anchors]])
        dists = shapely.distance(shapely.boundary([a.target for a in anchors]), pts)
        anchor_rms = float(np.sqrt(np.mean(np.asarray(dists) ** 2)))
    crossing = cand.links_crossing
    if with_links and links:
        lines = shapely.linestrings([[cams[a], cams[b]] for a, b in links])
        crossing = float(np.mean(shapely.intersects(shrunk, lines)))
    return Candidate(cand.transform, cand.score, inside, crossing, anchor_rms)


def search(
    walls: FloatArray,
    cameras: FloatArray,
    score_map: Raster,
    footprints: BaseGeometry,
    scale_prior: float,
    yaw_step_deg: float = 2.0,
    scale_factors: Sequence[float] = (0.75, 0.85, 0.95, 1.05, 1.15, 1.3),
    centre_window_m: float | None = None,
    anchors: Sequence[Anchor] = (),
    links: Sequence[tuple[int, int]] = (),
    peaks_per_pose: int = 3,
    top_k: int = 8,
) -> list[Candidate]:
    """Exhaustive yaw/scale search with FFT shifts, ranked by plausibility.

    ``cameras`` are raw model xy; returned transforms map raw model xy to map xy.
    """
    centroid = walls.mean(axis=0)
    rel_walls = walls - centroid
    origin = np.asarray(score_map.origin)
    min_sep = 10.0 / score_map.cell
    pool: list[Candidate] = []
    for scale in (scale_prior * f for f in scale_factors):
        for yaw_deg in np.arange(0.0, 360.0, yaw_step_deg):
            probe = Similarity2D(math.radians(yaw_deg), scale, (0.0, 0.0))
            grid, lo = _point_raster(probe.apply(rel_walls), score_map.cell)
            corr = fftconvolve(score_map.data, grid[::-1, ::-1], mode="valid")
            if corr.size == 0:
                continue
            if centre_window_m is not None:
                # keep the model centroid within the window around the map centre
                yy, xx = np.mgrid[0 : corr.shape[0], 0 : corr.shape[1]]
                cx = origin[0] + xx * score_map.cell - lo[0]
                cy = origin[1] + yy * score_map.cell - lo[1]
                corr = np.where(np.hypot(cx, cy) <= centre_window_m, corr, -np.inf)
            for r, c in _top_peaks(corr, peaks_per_pose, min_sep):
                shift = (
                    float(origin[0] + c * score_map.cell - lo[0]),
                    float(origin[1] + r * score_map.cell - lo[1]),
                )
                transform = _with_centroid(
                    Similarity2D(probe.yaw, scale, shift), centroid
                )
                pool.append(Candidate(transform, float(corr[r, c]) / len(walls)))
    shrunk = footprints.buffer(-0.75)
    shapely.prepare(footprints)
    shapely.prepare(shrunk)
    staged = [
        constrain(c, cameras, footprints, shrunk, anchors, links, with_links=False)
        for c in pool
    ]
    staged.sort(key=lambda c: -c.rank_value)
    final = [
        constrain(c, cameras, footprints, shrunk, anchors, links)
        for c in staged[: max(top_k * 25, 50)]
    ]
    final.sort(key=lambda c: -c.rank_value)
    return final[:top_k]


def _with_centroid(t: Similarity2D, centroid: FloatArray) -> Similarity2D:
    """Fold the centroid subtraction back into the shift (input: raw model xy)."""
    moved = t.apply(-centroid[None, :])[0]
    return Similarity2D(t.yaw, t.scale, (float(moved[0]), float(moved[1])))


@dataclass(frozen=True, slots=True)
class IcpResult:
    transform: Similarity2D
    rms_m: float
    inlier_ratio: float


def icp_refine(
    walls: FloatArray,
    outline_xy: FloatArray,
    init: Similarity2D,
    iterations: int = 40,
    trim_m: float = 2.0,
) -> IcpResult:
    """Trimmed point-to-point ICP with scale (Umeyama) in 2D."""
    tree = KDTree(outline_xy)
    t = init
    for _ in range(iterations):
        moved = t.apply(walls)
        dist, idx = tree.query(moved)
        keep = dist < trim_m
        if keep.sum() < 10:
            break
        t = umeyama_2d(walls[keep], outline_xy[idx[keep]])
    moved = t.apply(walls)
    dist, _ = tree.query(moved)
    inliers = dist < trim_m
    rms = float(np.sqrt(np.mean(dist[inliers] ** 2))) if inliers.any() else math.inf
    return IcpResult(t, rms, float(inliers.mean()))


def umeyama_2d(src: FloatArray, dst: FloatArray) -> Similarity2D:
    """Least-squares similarity dst ~= s R src + t (Umeyama 1991), 2D."""
    mu_s, mu_d = src.mean(axis=0), dst.mean(axis=0)
    a, b = src - mu_s, dst - mu_d
    cov = b.T @ a / len(src)
    u, d, vt = np.linalg.svd(cov)
    sign = np.diag([1.0, np.sign(np.linalg.det(u @ vt))])
    rot = u @ sign @ vt
    var_s = float(np.mean(np.sum(a**2, axis=1)))
    scale = float(np.trace(np.diag(d) @ sign)) / var_s
    shift = mu_d - scale * rot @ mu_s
    yaw = math.atan2(rot[1, 0], rot[0, 0])
    return Similarity2D(yaw, scale, (float(shift[0]), float(shift[1])))


def footprint_union(outlines: Sequence[Polygon]) -> BaseGeometry:
    return unary_union(list(outlines))
