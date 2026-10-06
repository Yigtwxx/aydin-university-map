"""Spike gates G2-G5 and metric sanity checks on a sparse reconstruction.

Pure functions work on plain numpy data (testable without pycolmap);
``extract_poses`` adapts a ``pycolmap.Reconstruction``.

- Gravity: panoramas are levelled, so each rig's +y axis (image "down") points
  along gravity. The mean over frames is the world down vector.
- Scale: the tripod height is ~1.6 m. The nadir is patched and never matches, so
  the camera height comes from distant ground features (curbs, paving lines) seen
  2-30 deg below the horizon: they sit lowest, so a high quantile of their
  depth below the camera is the camera height in model units.
- Heading: yaw of each pano's front axis in the horizontal plane, compared with
  the tour's per-scene angle ``p28`` to test whether it is a compass heading.
"""

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

FloatArray = NDArray[np.float64]

TRIPOD_HEIGHT_M = 1.6
# Fonts with Turkish glyphs (macOS, Debian/Ubuntu); PIL's default lacks ü/ş/ğ.
_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_GROUND_MIN_DEG, _GROUND_MAX_DEG = 2.0, 30.0
_GROUND_QUANTILE = 0.9
_MIN_GROUND_POINTS = 15


@dataclass(frozen=True, slots=True)
class PanoPose:
    scene: str
    center: FloatArray  # world position of the panorama centre (model units)
    rig_from_world: FloatArray  # 3x3 rotation
    points: FloatArray  # (N, 3) world points observed by any face of this pano


def world_axis(pose: PanoPose, axis: int) -> FloatArray:
    """Rig axis ``axis`` (0=x right, 1=y down, 2=z front) in world coordinates."""
    return pose.rig_from_world[axis]


def gravity(poses: Sequence[PanoPose]) -> tuple[FloatArray, float]:
    """World down vector and the median per-pano deviation from it (degrees)."""
    downs = np.array([world_axis(p, 1) for p in poses])
    mean = downs.mean(axis=0)
    mean /= np.linalg.norm(mean)
    deviations = np.degrees(np.arccos(np.clip(downs @ mean, -1.0, 1.0)))
    return mean, float(np.median(deviations))


def camera_height(pose: PanoPose, down: FloatArray) -> float | None:
    """Camera height above the ground in model units, or None if unobserved."""
    if len(pose.points) == 0:
        return None
    offsets = pose.points - pose.center
    below = offsets @ down
    horizontal = np.linalg.norm(offsets - np.outer(below, down), axis=1)
    angle = np.degrees(np.arctan2(below, horizontal))
    ground = below[(angle > _GROUND_MIN_DEG) & (angle < _GROUND_MAX_DEG)]
    if len(ground) < _MIN_GROUND_POINTS:
        return None
    return float(np.quantile(ground, _GROUND_QUANTILE))


@dataclass(frozen=True, slots=True)
class ScaleEstimate:
    metres_per_unit: float
    heights_units: dict[str, float]
    cv: float  # robust coefficient of variation (1.4826 * MAD / median)


def metric_scale(
    poses: Sequence[PanoPose], down: FloatArray, tripod_m: float = TRIPOD_HEIGHT_M
) -> ScaleEstimate | None:
    heights: dict[str, float] = {}
    for pose in poses:
        height = camera_height(pose, down)
        if height is not None and height > 0:
            heights[pose.scene] = height
    if len(heights) < 3:
        return None
    values = list(heights.values())
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    return ScaleEstimate(tripod_m / median, heights, 1.4826 * mad / median)


def horizontal_basis(down: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Horizontal unit axes (e1, e2) with cross(e1, e2) = -down (right-handed)."""
    seed = (
        np.array([1.0, 0.0, 0.0]) if abs(down[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
    )
    e1 = seed - (seed @ down) * down
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(-down, e1)
    return e1, e2


def yaw_deg(pose: PanoPose, down: FloatArray) -> float:
    """Heading of the pano front axis, counter-clockwise from e1 seen from above."""
    e1, e2 = horizontal_basis(down)
    front = world_axis(pose, 2)
    return math.degrees(math.atan2(float(front @ e2), float(front @ e1))) % 360.0


def _wrap180(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


@dataclass(frozen=True, slots=True)
class HeadingCheck:
    sign: int  # +1: p28 grows counter-clockwise, -1: clockwise (compass-like)
    offset_deg: float
    median_abs_residual_deg: float
    residuals: dict[str, float]


def p28_consistency(
    yaws: Mapping[str, float], p28: Mapping[str, float]
) -> HeadingCheck | None:
    """Test whether p28 = sign * yaw + offset for a single global offset."""
    common = [s for s in yaws if s in p28]
    if len(common) < 3:
        return None
    best: HeadingCheck | None = None
    for sign in (1, -1):
        diffs = [math.radians(p28[s] - sign * yaws[s]) for s in common]
        offset = math.degrees(
            math.atan2(sum(map(math.sin, diffs)), sum(map(math.cos, diffs)))
        )
        residuals = {s: _wrap180(p28[s] - sign * yaws[s] - offset) for s in common}
        med = statistics.median(abs(r) for r in residuals.values())
        check = HeadingCheck(sign, offset % 360.0, med, residuals)
        if best is None or med < best.median_abs_residual_deg:
            best = check
    return best


def edge_lengths_m(
    poses: Sequence[PanoPose], edges: Iterable[tuple[str, str]], metres_per_unit: float
) -> dict[tuple[str, str], float]:
    centers = {p.scene: p.center for p in poses}
    lengths: dict[tuple[str, str], float] = {}
    for a, b in edges:
        if a in centers and b in centers:
            dist = float(np.linalg.norm(centers[a] - centers[b])) * metres_per_unit
            lengths[(a, b)] = dist
    return lengths


def plot_topdown(
    poses: Sequence[PanoPose],
    edges: Iterable[tuple[str, str]],
    down: FloatArray,
    metres_per_unit: float,
    labels: Mapping[str, str],
    path: Path,
    size: int = 1400,
) -> None:
    """Debug PNG of the trajectory seen from above, with tour links and a 10 m bar."""
    e1, e2 = horizontal_basis(down)
    xy = {
        p.scene: np.array([p.center @ e1, p.center @ e2]) * metres_per_unit
        for p in poses
    }
    pts = np.array(list(xy.values()))
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    span = float(max(hi - lo)) or 1.0
    margin = 60

    def to_px(v: FloatArray) -> tuple[float, float]:
        q = (v - lo) / span * (size - 2 * margin) + margin
        return float(q[0]), float(size - q[1])  # y up

    img = Image.new("RGB", (size, size), (250, 250, 248))
    draw = ImageDraw.Draw(img)
    font = _label_font(14)
    for a, b in edges:
        if a in xy and b in xy:
            draw.line([to_px(xy[a]), to_px(xy[b])], fill=(170, 170, 170), width=2)
    for scene, v in xy.items():
        x, y = to_px(v)
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(30, 90, 200))
        draw.text(
            (x + 7, y - 8), labels.get(scene, scene)[:22], fill=(40, 40, 40), font=font
        )
    bar = 10.0 / span * (size - 2 * margin)
    draw.line([(margin, size - 30), (margin + bar, size - 30)], fill=(0, 0, 0), width=4)
    draw.text((margin, size - 52), "10 m", fill=(0, 0, 0), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def extract_poses(rec: Any) -> list[PanoPose]:
    """Build ``PanoPose`` objects from a pycolmap Reconstruction."""
    poses: list[PanoPose] = []
    for frame_id in rec.reg_frame_ids():
        frame = rec.frame(frame_id)
        rig_from_world = frame.rig_from_world
        rotation = np.asarray(rig_from_world.rotation.matrix(), dtype=np.float64)
        translation = np.asarray(rig_from_world.translation, dtype=np.float64)
        scene: str | None = None
        point_ids: set[int] = set()
        for data_id in frame.data_ids:
            image = rec.image(data_id.id)
            scene = image.name.split("/", 1)[1].removesuffix(".jpg")
            point_ids.update(p.point3D_id for p in image.points2D if p.has_point3D())
        if scene is None:
            continue
        points = np.array([rec.point3D(i).xyz for i in sorted(point_ids)])
        poses.append(
            PanoPose(
                scene=scene,
                center=-rotation.T @ translation,
                rig_from_world=rotation,
                points=points.reshape(-1, 3),
            )
        )
    return poses
