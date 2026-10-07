"""Render views of a panorama from its six local cube faces.

Faces stay uint8 (a 1300² scene is ~30 MB; ``cubemap.load_faces`` makes float64
copies, ~240 MB) and a small LRU keeps the scenes a walk revisits.
"""

import math
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from amap_pipeline.look.camera import FloatArray, rig_rays
from amap_pipeline.recon.cubemap import CAM_FROM_RIG, FACES

ByteImage = NDArray[np.uint8]


class FaceCache:
    """uint8 cube faces per scene from ``data/tiles`` (JPEG) or ``data/out/panos``."""

    def __init__(self, roots: list[Path], capacity: int = 6) -> None:
        self.roots = roots
        self.capacity = capacity
        self._scenes: OrderedDict[str, dict[str, ByteImage]] = OrderedDict()

    def faces(self, scene: str) -> dict[str, ByteImage]:
        if scene in self._scenes:
            self._scenes.move_to_end(scene)
            return self._scenes[scene]
        faces = self._load(scene)
        self._scenes[scene] = faces
        while len(self._scenes) > self.capacity:
            self._scenes.popitem(last=False)
        return faces

    def _load(self, scene: str) -> dict[str, ByteImage]:
        for root in self.roots:
            folder = root / scene
            for ext in ("jpg", "webp"):
                files = {face: folder / f"{face}.{ext}" for face in FACES}
                if all(p.is_file() for p in files.values()):
                    out: dict[str, ByteImage] = {}
                    for face, path in files.items():
                        with Image.open(path) as img:
                            out[face] = np.asarray(img.convert("RGB"), dtype=np.uint8)
                    return out
        raise FileNotFoundError(f"{scene}: no cube faces under {self.roots}")


def sample_rays(faces: Mapping[str, ByteImage], dirs: FloatArray) -> ByteImage:
    """Bilinear colours (N, 3) of rig directions (N, 3)."""
    d = np.asarray(dirs, dtype=np.float64).reshape(-1, 3)
    out = np.zeros((d.shape[0], 3), dtype=np.float32)
    # Each ray belongs to the face its dominant axis points through.
    axis = np.argmax(np.abs(d), axis=1)
    positive = d[np.arange(d.shape[0]), axis] > 0
    owner = {
        (0, True): "r",
        (0, False): "l",
        (1, True): "d",
        (1, False): "u",
        (2, True): "f",
        (2, False): "b",
    }
    for (ax, pos), face in owner.items():
        mask = (axis == ax) & (positive == pos)
        if not mask.any():
            continue
        image = faces[face]
        size = image.shape[0]
        cam = d[mask] @ CAM_FROM_RIG[face].T
        half = size / 2.0
        u = half * cam[:, 0] / cam[:, 2] + half
        v = half * cam[:, 1] / cam[:, 2] + half
        out[mask] = _bilinear(image, u, v)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def _bilinear(image: ByteImage, u: FloatArray, v: FloatArray) -> NDArray[np.float32]:
    h, w = image.shape[:2]
    x = np.clip(u - 0.5, 0.0, w - 1.0)
    y = np.clip(v - 0.5, 0.0, h - 1.0)
    x0 = np.floor(x).astype(np.intp)
    y0 = np.floor(y).astype(np.intp)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (x - x0).astype(np.float32)[:, None]
    fy = (y - y0).astype(np.float32)[:, None]

    def at(rows: NDArray[np.intp], cols: NDArray[np.intp]) -> NDArray[np.float32]:
        return image[rows, cols].astype(np.float32)

    top = at(y0, x0) * (1 - fx) + at(y0, x1) * fx
    bottom = at(y1, x0) * (1 - fx) + at(y1, x1) * fx
    return (top * (1 - fy) + bottom * fy).astype(np.float32)


@dataclass(frozen=True, slots=True)
class View:
    """A rectilinear camera inside the panorama (no roll)."""

    ath_deg: float  # centre direction, clockwise from the front face
    atv_deg: float  # centre pitch, positive = down
    hfov_deg: float
    width: int
    height: int

    @property
    def focal_px(self) -> float:
        return (self.width / 2.0) / math.tan(math.radians(self.hfov_deg) / 2.0)

    def axes(self) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Rig unit vectors of the view's right, down and forward axes."""
        forward = rig_rays(np.array([self.ath_deg]), np.array([self.atv_deg]))[0]
        right = rig_rays(np.array([self.ath_deg + 90.0]), np.array([0.0]))[0]
        down = np.cross(forward, right)
        return right, down, forward

    def pixel_rays(self) -> FloatArray:
        """Rig directions (H*W, 3) through every pixel centre."""
        right, down, forward = self.axes()
        f = self.focal_px
        xs = (np.arange(self.width) + 0.5 - self.width / 2.0) / f
        ys = (np.arange(self.height) + 0.5 - self.height / 2.0) / f
        gx, gy = np.meshgrid(xs, ys)
        rays = gx.reshape(-1, 1) * right + gy.reshape(-1, 1) * down + forward[None, :]
        return rays / np.linalg.norm(rays, axis=1, keepdims=True)

    def to_pixels(self, dirs: FloatArray) -> tuple[FloatArray, NDArray[np.bool_]]:
        """Pixel coordinates (N, 2) of rig directions and whether they are in front."""
        right, down, forward = self.axes()
        d = np.asarray(dirs, dtype=np.float64).reshape(-1, 3)
        z = d @ forward
        front = z > 1e-6
        safe = np.where(front, z, 1.0)
        f = self.focal_px
        u = f * (d @ right) / safe + self.width / 2.0
        v = f * (d @ down) / safe + self.height / 2.0
        return np.stack([u, v], axis=1), front


def render_view(faces: Mapping[str, ByteImage], view: View) -> ByteImage:
    colours = sample_rays(faces, view.pixel_rays())
    return colours.reshape(view.height, view.width, 3)


@dataclass(frozen=True, slots=True)
class Strip:
    """An equirectangular band: ath across, atv down."""

    ath_start_deg: float
    ath_span_deg: float
    atv_top_deg: float  # negative = above the horizon
    atv_bottom_deg: float
    px_per_deg: float

    @property
    def width(self) -> int:
        return round(self.ath_span_deg * self.px_per_deg)

    @property
    def height(self) -> int:
        return round((self.atv_bottom_deg - self.atv_top_deg) * self.px_per_deg)

    def angles(self) -> tuple[FloatArray, FloatArray]:
        cols = np.arange(self.width, dtype=np.float64) + 0.5
        rows = np.arange(self.height, dtype=np.float64) + 0.5
        ath = self.ath_start_deg + cols / self.px_per_deg
        atv = self.atv_top_deg + rows / self.px_per_deg
        return ath, atv

    def to_pixels(self, ath: FloatArray, atv: FloatArray) -> FloatArray:
        """Pixel (u, v) of angles; ath wraps into the strip's window."""
        rel = (np.asarray(ath, dtype=np.float64) - self.ath_start_deg) % 360.0
        u = rel * self.px_per_deg
        v = (np.asarray(atv, dtype=np.float64) - self.atv_top_deg) * self.px_per_deg
        return np.stack([u, v], axis=-1)


def render_strip(faces: Mapping[str, ByteImage], strip: Strip) -> ByteImage:
    ath, atv = strip.angles()
    ga, gv = np.meshgrid(ath, atv)
    colours = sample_rays(faces, rig_rays(ga.ravel(), gv.ravel()))
    return colours.reshape(strip.height, strip.width, 3)
