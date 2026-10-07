"""Top-down map around one panorama: footprints, paths, neighbours, view wedge."""

import math
from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageDraw

from amap_pipeline.look.camera import Pose
from amap_pipeline.look.context import LookContext
from amap_pipeline.look.overlay import Mark
from amap_pipeline.recon.evaluate import label_font

_GROUND_COLOURS = {
    "footway": (190, 170, 140),
    "steps": (220, 90, 60),
    "pedestrian": (200, 185, 160),
}


def render_plan(
    ctx: LookContext,
    pose: Pose,
    *,
    radius_m: float = 70.0,
    size: int = 760,
    view_ath_deg: float | None = None,
    hfov_deg: float | None = None,
    marks: Sequence[Mark] = (),
    rays: Sequence[tuple[str, float]] = (),
) -> Image.Image:
    """North-up plan centred on ``pose``; ``rays`` are (label, ath) bearings."""
    image = Image.new("RGB", (size, size), (247, 246, 242))
    draw = ImageDraw.Draw(image)
    scale = size / (2.0 * radius_m)
    font = label_font(13)
    small = label_font(11)

    def px(x: float, y: float) -> tuple[float, float]:
        return (
            size / 2.0 + (x - pose.x) * scale,
            size / 2.0 - (y - pose.y) * scale,
        )

    for g in ctx.ground:
        d = np.hypot(g.line[:, 0] - pose.x, g.line[:, 1] - pose.y)
        if float(d.min()) > radius_m * 1.5:
            continue
        colour = _GROUND_COLOURS.get(g.kind, (215, 215, 215))
        draw.line([px(x, y) for x, y in g.line], fill=colour, width=2)
    for b in ctx.buildings_near(pose.x, pose.y, radius_m * 1.5):
        ring = [px(x, y) for x, y in b.outline]
        fill = (238, 222, 170) if b.campus else (222, 222, 222)
        draw.polygon(ring, fill=fill, outline=(110, 110, 110))
        for i, (x, y) in enumerate(b.outline):
            if math.hypot(x - pose.x, y - pose.y) <= radius_m:
                draw.text(px(x, y), f"{i}", fill=(120, 90, 0), font=small)
        cx, cy = b.outline.mean(axis=0)
        draw.text(px(cx, cy), b.code, fill=(60, 60, 60), font=font, anchor="mm")
    for scene, other in ctx.poses.items():
        if ctx.pose_sources.get(scene) == "interpolated" or scene == pose.scene:
            continue
        if math.hypot(other.x - pose.x, other.y - pose.y) > radius_m:
            continue
        x, y = px(other.x, other.y)
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(220, 50, 150))
        draw.text((x + 5, y - 6), scene.removeprefix("scene_"), fill=(150, 30, 100))
    cx, cy = size / 2.0, size / 2.0
    reach = radius_m * scale
    if view_ath_deg is not None and hfov_deg is not None:
        for edge in (-hfov_deg / 2.0, hfov_deg / 2.0):
            b = math.radians(pose.heading_deg + view_ath_deg + edge)
            draw.line(
                [(cx, cy), (cx + reach * math.sin(b), cy - reach * math.cos(b))],
                fill=(40, 120, 230),
                width=2,
            )
    for label, ath in rays:
        b = math.radians(pose.heading_deg + ath)
        end = (cx + reach * math.sin(b), cy - reach * math.cos(b))
        draw.line([(cx, cy), end], fill=(30, 170, 70), width=2)
        draw.text(end, label, fill=(20, 120, 50), font=small)
    for m in marks:
        x, y = px(m.x, m.y)
        draw.rectangle((x - 4, y - 4, x + 4, y + 4), fill=(30, 170, 70))
        draw.text((x + 6, y - 6), m.label, fill=(20, 120, 50), font=small)
    # The camera and its front face (ath 0).
    front = math.radians(pose.heading_deg)
    draw.line(
        [(cx, cy), (cx + 22 * math.sin(front), cy - 22 * math.cos(front))],
        fill=(220, 30, 30),
        width=3,
    )
    draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=(220, 30, 30))
    draw.text((10, 8), f"N ↑   {pose.scene}", fill=(30, 30, 30), font=font)
    bar = 10.0 * scale
    draw.line([(10, size - 16), (10 + bar, size - 16)], fill=(0, 0, 0), width=4)
    draw.text((10, size - 36), "10 m", fill=(0, 0, 0), font=small)
    return image
