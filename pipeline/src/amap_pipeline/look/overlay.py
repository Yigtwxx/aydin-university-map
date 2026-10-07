"""Draw the map into a panorama view: grid, footprints, neighbours, tour arrows.

If the pose is right, footprint corners sit on the real building corners and
neighbour markers stand where those panoramas were taken. That picture is the
evidence the survey keeps for each scene.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from amap_pipeline.look.camera import (
    FloatArray,
    Pose,
    enu_to_rig,
    rig_angles,
    rig_rays,
)
from amap_pipeline.look.context import LookContext
from amap_pipeline.look.render import Strip, View
from amap_pipeline.recon.evaluate import label_font

BoolArray = NDArray[np.bool_]
RGBA = tuple[int, int, int, int]

GRID: RGBA = (255, 255, 255, 120)
GRID_MAJOR: RGBA = (255, 255, 255, 200)
CAMPUS: RGBA = (255, 214, 0, 235)
OTHER: RGBA = (0, 214, 255, 200)
NODE: RGBA = (255, 70, 170, 240)
ARROW: RGBA = (255, 140, 0, 245)
MARK: RGBA = (90, 255, 120, 245)
HOTSPOT_ATV_DEG = 25.0  # tour arrows lie on the floor, about this far down


class Canvas(Protocol):
    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    @property
    def wraps(self) -> bool: ...

    def project(self, dirs: FloatArray) -> tuple[FloatArray, BoolArray]: ...


@dataclass(frozen=True, slots=True)
class ViewCanvas:
    view: View

    @property
    def width(self) -> int:
        return self.view.width

    @property
    def height(self) -> int:
        return self.view.height

    @property
    def wraps(self) -> bool:
        return False

    def project(self, dirs: FloatArray) -> tuple[FloatArray, BoolArray]:
        uv, front = self.view.to_pixels(dirs)
        margin = max(self.width, self.height)
        inside = (
            front
            & (uv[:, 0] > -margin)
            & (uv[:, 0] < self.width + margin)
            & (uv[:, 1] > -margin)
            & (uv[:, 1] < self.height + margin)
        )
        return uv, inside


@dataclass(frozen=True, slots=True)
class StripCanvas:
    strip: Strip

    @property
    def width(self) -> int:
        return self.strip.width

    @property
    def height(self) -> int:
        return self.strip.height

    @property
    def wraps(self) -> bool:
        return self.strip.ath_span_deg >= 359.0

    def project(self, dirs: FloatArray) -> tuple[FloatArray, BoolArray]:
        ath, atv = rig_angles(dirs)
        uv = self.strip.to_pixels(ath, atv)
        inside = (uv[:, 0] >= 0) & (uv[:, 0] <= self.width)
        return uv, inside


class Painter:
    """Accumulates translucent strokes over a rendered view."""

    def __init__(self, image: NDArray[np.uint8], canvas: Canvas) -> None:
        self.base = Image.fromarray(image).convert("RGBA")
        self.layer = Image.new("RGBA", self.base.size, (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)
        self.canvas = canvas
        self.font = label_font(15)
        self.small = label_font(12)

    def result(self) -> Image.Image:
        return Image.alpha_composite(self.base, self.layer).convert("RGB")

    def polyline(self, dirs: FloatArray, colour: RGBA, width: int = 2) -> None:
        uv, ok = self.canvas.project(dirs)
        jump = self.canvas.width / 2.0
        for i in range(len(uv) - 1):
            if not (ok[i] and ok[i + 1]):
                continue
            (u0, v0), (u1, v1) = uv[i], uv[i + 1]
            if self.canvas.wraps and abs(u1 - u0) > jump:
                continue
            self.draw.line([(u0, v0), (u1, v1)], fill=colour, width=width)

    def text(
        self,
        dirs: FloatArray,
        label: str,
        colour: RGBA,
        *,
        dy: float = 0.0,
        small: bool = False,
    ) -> None:
        uv, ok = self.canvas.project(dirs.reshape(1, 3))
        if not ok[0]:
            return
        u, v = float(uv[0, 0]), float(uv[0, 1]) + dy
        if not (-50 < u < self.canvas.width + 50 and -20 < v < self.canvas.height):
            return
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont = (
            self.small if small else self.font
        )
        self.draw.text(
            (u + 4, v),
            label,
            fill=colour,
            font=font,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 220),
        )

    def dot(self, dirs: FloatArray, colour: RGBA, radius: float = 5.0) -> None:
        uv, ok = self.canvas.project(dirs.reshape(1, 3))
        if ok[0]:
            u, v = float(uv[0, 0]), float(uv[0, 1])
            self.draw.ellipse(
                (u - radius, v - radius, u + radius, v + radius),
                fill=colour,
                outline=(0, 0, 0, 255),
            )


def _ath_line(ath: float, atv_from: float, atv_to: float, n: int = 90) -> FloatArray:
    atv = np.linspace(atv_from, atv_to, n)
    return rig_rays(np.full(n, ath), atv)


def _atv_line(atv: float, ath_from: float, ath_to: float, n: int = 361) -> FloatArray:
    ath = np.linspace(ath_from, ath_to, n)
    return rig_rays(ath, np.full(n, atv))


def draw_grid(
    p: Painter,
    pose: Pose | None,
    *,
    step_deg: float = 5.0,
    label_every: int = 2,
    label_atv_deg: float = -30.0,
) -> None:
    """Lines of constant ath (labelled ``ath`` and, with a pose, compass bearing)."""
    decimals = 0 if step_deg * label_every >= 1.0 else 1
    for i, ath in enumerate(np.arange(0.0, 360.0, step_deg)):
        major = i % label_every == 0
        p.polyline(_ath_line(ath, -80, 80), GRID_MAJOR if major else GRID, 1)
        if major:
            top = rig_rays(np.array([ath]), np.array([label_atv_deg]))[0]
            label = f"{ath:.{decimals}f}"
            # Fine grids (zoomed views) carry ath alone; bearings would collide.
            if pose is not None and step_deg > 1.0:
                label += f" | B{(ath + pose.heading_deg) % 360:.{decimals}f}"
            p.text(top, label, GRID_MAJOR, small=True)
    for atv in (-30.0, -15.0, 0.0, 15.0, 30.0, 45.0):
        p.polyline(_atv_line(atv, 0, 360), GRID_MAJOR if atv == 0 else GRID, 1)


def _densify(points: FloatArray, step_m: float = 0.5) -> FloatArray:
    out: list[FloatArray] = []
    for a, b in pairwise(points):
        n = max(int(np.linalg.norm(b - a) / step_m), 1)
        t = np.linspace(0.0, 1.0, n, endpoint=False)[:, None]
        out.append(a + (b - a) * t)
    out.append(points[-1:])
    return np.vstack(out)


def draw_buildings(
    p: Painter,
    ctx: LookContext,
    pose: Pose,
    *,
    radius_m: float = 90.0,
    label_radius_m: float = 60.0,
    outlines: bool = True,
    corners: bool = True,
) -> None:
    """Footprints at ground level, roof edges and numbered corner verticals.

    Corner ``CODE#i`` is vertex ``i`` of the outline in buildings.json: the
    landmark name an observation refers to.
    """
    ground = pose.ground_z
    for b in ctx.buildings_near(pose.x, pose.y, radius_m):
        colour = CAMPUS if b.campus else OTHER
        if outlines:
            ring = np.vstack([b.outline, b.outline[:1]])
            base = _densify(np.column_stack([ring, np.full(len(ring), ground)]))
            roof = base.copy()
            roof[:, 2] = ground + b.height_m
            p.polyline(enu_to_rig(pose, base), colour, 2)
            p.polyline(enu_to_rig(pose, roof), colour, 1)
        if not corners:
            continue
        for i, (x, y) in enumerate(b.outline):
            dist = float(np.hypot(x - pose.x, y - pose.y))
            if dist > label_radius_m:
                continue
            column = np.column_stack(
                [
                    np.full(12, x),
                    np.full(12, y),
                    np.linspace(ground, ground + b.height_m, 12),
                ]
            )
            p.polyline(enu_to_rig(pose, column), colour, 1 if outlines else 2)
            label = f"{b.code}#{i} {dist:.0f}m"
            # At the roof line for whole-panorama strips, and at eye height so a
            # zoomed view still names the line.
            for z in (ground + b.height_m, pose.z):
                point = enu_to_rig(pose, np.array([[x, y, z]]))[0]
                p.text(point, label, colour, small=True)


def draw_nodes(
    p: Painter, ctx: LookContext, pose: Pose, *, radius_m: float = 60.0
) -> None:
    """Other measured panoramas: a stick from their ground up to their camera."""
    for scene, other in ctx.poses.items():
        if scene == pose.scene or ctx.pose_sources.get(scene) == "interpolated":
            continue
        dist = float(np.hypot(other.x - pose.x, other.y - pose.y))
        if dist > radius_m or dist < 0.5:
            continue
        stick = np.array(
            [[other.x, other.y, other.ground_z], [other.x, other.y, other.z]]
        )
        rig = enu_to_rig(pose, stick)
        p.polyline(rig, NODE, 2)
        p.dot(rig[0], NODE, 4)
        label = f"{scene.removeprefix('scene_')} {ctx.label(scene)[:18]} {dist:.0f}m"
        p.text(rig[1], label, NODE, small=True)


def draw_hotspots(p: Painter, ctx: LookContext, scene: str) -> None:
    """The tour's own arrows at their ``ath`` (pose independent)."""
    for target, ath in sorted(ctx.link_yaw.get(scene, {}).items()):
        ray = rig_rays(np.array([ath]), np.array([HOTSPOT_ATV_DEG]))[0]
        p.dot(ray, ARROW, 7)
        p.polyline(
            _ath_line(ath, HOTSPOT_ATV_DEG - 6, HOTSPOT_ATV_DEG + 6, 8), ARROW, 3
        )
        label = f"→ {target.removeprefix('scene_')} {ctx.label(target)[:18]}"
        p.text(ray, label, ARROW, dy=8)


@dataclass(frozen=True, slots=True)
class Mark:
    label: str
    x: float
    y: float
    z: float | None = None  # None: at the camera's ground


def draw_marks(p: Painter, pose: Pose, marks: Sequence[Mark]) -> None:
    for m in marks:
        z = pose.ground_z if m.z is None else m.z
        rig = enu_to_rig(pose, np.array([[m.x, m.y, z], [m.x, m.y, z + 3.0]]))
        p.polyline(rig, MARK, 3)
        p.dot(rig[0], MARK, 5)
        p.text(rig[1], m.label, MARK)


def draw_ath_marks(p: Painter, aths: Sequence[tuple[str, float]]) -> None:
    """Vertical markers at given ``ath`` values (observations being checked)."""
    for label, ath in aths:
        p.polyline(_ath_line(ath, -60, 60), MARK, 2)
        p.text(rig_rays(np.array([ath]), np.array([-20.0]))[0], label, MARK)
