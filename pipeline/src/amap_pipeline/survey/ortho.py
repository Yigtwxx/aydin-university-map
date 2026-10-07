"""Ground orthomosaic: the paving seen from above, stitched from panoramas.

Every map pixel (x, y) on level ground is looked up in the panoramas around it:
the ray from a camera down to (x, y, ground) gives an ``(ath, atv)`` and so a
colour. Nearer cameras see the ground sharper, so they weigh more.

Two uses. Steps, kerbs, railings' feet and benches are drawn straight in map
coordinates on it. And it checks poses: where two panoramas overlap, their
pictures of the same paving agree only if both poses (and the tripod height)
are right; a ghosted pattern is a wrong pose.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from amap_pipeline.look.camera import FloatArray, Pose, enu_to_rig
from amap_pipeline.look.render import ByteImage, sample_rays

# Too close: the tripod and its shadow (the nadir patch). Too far: smeared.
MIN_RANGE_M = 1.8
MAX_RANGE_M = 14.0


@dataclass(frozen=True, slots=True)
class Grid:
    x0: float  # west edge, local metres
    y0: float  # south edge
    x1: float
    y1: float
    res_m: float

    @property
    def width(self) -> int:
        return round((self.x1 - self.x0) / self.res_m)

    @property
    def height(self) -> int:
        return round((self.y1 - self.y0) / self.res_m)

    def centres(self) -> tuple[FloatArray, FloatArray]:
        """Pixel-centre coordinates (H, W), row 0 at the north edge."""
        xs = self.x0 + (np.arange(self.width, dtype=np.float64) + 0.5) * self.res_m
        ys = self.y1 - (np.arange(self.height, dtype=np.float64) + 0.5) * self.res_m
        gx, gy = np.meshgrid(xs, ys)
        return gx.astype(np.float64), gy.astype(np.float64)

    def to_pixel(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.x0) / self.res_m, (self.y1 - y) / self.res_m


@dataclass(frozen=True, slots=True)
class Layer:
    """One panorama's view of the ground over the grid."""

    scene: str
    colour: NDArray[np.float32]  # (H, W, 3)
    weight: NDArray[np.float32]  # (H, W), 0 where the panorama sees nothing


def project_ground(
    faces: Mapping[str, ByteImage],
    pose: Pose,
    grid: Grid,
    *,
    min_range_m: float = MIN_RANGE_M,
    max_range_m: float = MAX_RANGE_M,
) -> Layer:
    gx, gy = grid.centres()
    dist = np.hypot(gx - pose.x, gy - pose.y)
    seen = (dist >= min_range_m) & (dist <= max_range_m)
    colour = np.zeros((grid.height, grid.width, 3), dtype=np.float32)
    weight = np.zeros((grid.height, grid.width), dtype=np.float32)
    if seen.any():
        points = np.column_stack(
            [gx[seen], gy[seen], np.full(int(seen.sum()), pose.ground_z)]
        )
        rays = enu_to_rig(pose, points)
        rays /= np.linalg.norm(rays, axis=1, keepdims=True)
        colour[seen] = sample_rays(faces, rays).astype(np.float32)
        # Ground resolution falls with the square of the distance.
        weight[seen] = (1.0 / np.maximum(dist[seen], 1.0) ** 2).astype(np.float32)
    return Layer(pose.scene, colour, weight)


def blend(layers: Sequence[Layer], grid: Grid, *, nearest: bool = True) -> ByteImage:
    """Mosaic: each pixel from its best panorama (or a weighted mean)."""
    out = np.full((grid.height, grid.width, 3), 255.0, dtype=np.float32)
    if not layers:
        return out.astype(np.uint8)
    weights = np.stack([layer.weight for layer in layers])
    colours = np.stack([layer.colour for layer in layers])
    covered = weights.max(axis=0) > 0
    if nearest:
        best = np.argmax(weights, axis=0)
        picked = np.take_along_axis(colours, best[None, :, :, None], axis=0)[0]
        out[covered] = picked[covered]
    else:
        total = weights.sum(axis=0)
        mean = (colours * weights[..., None]).sum(axis=0) / np.maximum(total, 1e-9)[
            ..., None
        ]
        out[covered] = mean[covered]
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def agreement(a: Layer, b: Layer, *, min_pixels: int = 400) -> float | None:
    """Normalised cross-correlation of two panoramas' views of the same ground.

    Near 1: they paint the same paving pattern in the same place. None when
    they overlap too little to say.
    """
    both = (a.weight > 0) & (b.weight > 0)
    if int(both.sum()) < min_pixels:
        return None
    grey = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    va = a.colour[both] @ grey
    vb = b.colour[both] @ grey
    va = va - va.mean()
    vb = vb - vb.mean()
    denom = float(np.sqrt((va * va).sum() * (vb * vb).sum()))
    if denom <= 0:
        return None
    return float((va * vb).sum() / denom)
