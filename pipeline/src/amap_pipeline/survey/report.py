"""The survey's evidence as one local HTML page (``data/debug/survey``).

For every panorama with sightings: the map drawn into its picture from the old
pose and from the solved one, with each sighting marked. When the solved pose
is right, footprint corners land on the marked edges. An overview map shows
how far each panorama moved and how sure the solve is (1-sigma ellipses).
"""

import html
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from amap_pipeline.look.camera import Pose
from amap_pipeline.look.context import LookContext
from amap_pipeline.look.overlay import (
    Painter,
    StripCanvas,
    draw_ath_marks,
    draw_buildings,
    draw_grid,
)
from amap_pipeline.look.render import Strip, render_strip
from amap_pipeline.recon.evaluate import label_font

CSS = (
    "body{font:14px system-ui;margin:24px;color:#222;background:#fafaf8}"
    "table{border-collapse:collapse;margin:12px 0}"
    "td,th{padding:3px 8px;border-bottom:1px solid #ddd;text-align:left}"
    ".pass{color:#0a7a2f;font-weight:600}.fail{color:#b3261e;font-weight:600}"
    "img{max-width:100%;display:block}section{margin:28px 0}"
    ".k{margin:6px 0 2px;color:#666}"
)

# Acceptance thresholds from the plan.
MAX_RMS_DEG = 0.7
MAX_HOLDOUT_DEG = 1.0
MAX_SIGMA_M = 1.5
MAX_HOTSPOT_DEG = 5.0


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    value: str
    ok: bool | None  # None: not measured


def acceptance(data: Mapping[str, Any]) -> list[Check]:
    summary = data["summary"]
    checks: list[Check] = []
    rms = summary.get("rms_sighting_deg")
    checks.append(
        Check(
            f"Sighting RMS < {MAX_RMS_DEG}°",
            "-" if rms is None else f"{rms:.2f}°",
            None if rms is None else rms < MAX_RMS_DEG,
        )
    )
    held = summary.get("holdout_median_deg")
    checks.append(
        Check(
            f"Held-out median < {MAX_HOLDOUT_DEG}°",
            "-" if held is None else f"{held:.2f}°",
            None if held is None else held < MAX_HOLDOUT_DEG,
        )
    )
    observed = [p for p in data["poses"].values() if p.get("sightings")]
    worst = max((p["ellipse"][0] for p in observed), default=None)
    checks.append(
        Check(
            f"Every measured panorama 1-sigma < {MAX_SIGMA_M} m",
            "-" if worst is None else f"worst {worst:.2f} m",
            None if worst is None else worst < MAX_SIGMA_M,
        )
    )
    by_model: dict[str, list[float]] = {}
    for r in data["residuals"]:
        if r["kind"] != "hotspot":
            continue
        pose = data["poses"].get(r["scene"])
        model = (pose or {}).get("model") or "free"
        by_model.setdefault(model, []).append(abs(r["residual_deg"]))
    for model, values in sorted(by_model.items()):
        values.sort()
        median = values[len(values) // 2]
        checks.append(
            Check(
                f"Tour arrows, {model}: median < {MAX_HOTSPOT_DEG}°",
                f"{median:.1f}° ({len(values)})",
                median < MAX_HOTSPOT_DEG,
            )
        )
    return checks


def _pose(record: Mapping[str, Any], scene: str, tripod: float) -> Pose:
    return Pose(
        scene=scene,
        x=float(record["x"]),
        y=float(record["y"]),
        z=float(record.get("z", tripod)),
        heading_deg=float(record["heading_deg"]),
        tripod_m=tripod,
    )


def evidence_strip(
    ctx: LookContext,
    scene: str,
    pose: Pose,
    marks: Sequence[tuple[str, float]],
    *,
    px_per_deg: float = 4.0,
) -> Image.Image:
    strip = Strip(0.0, 360.0, -30.0, 30.0, px_per_deg)
    painter = Painter(render_strip(ctx.faces.faces(scene), strip), StripCanvas(strip))
    draw_grid(painter, pose, step_deg=10.0, label_every=3)
    draw_buildings(painter, ctx, pose, outlines=False)
    draw_ath_marks(painter, marks)
    return painter.result()


def overview_map(
    ctx: LookContext, data: Mapping[str, Any], *, width: int = 1400
) -> Image.Image:
    """Old -> solved positions, 1-sigma ellipses (x5 so they show) and tie points."""
    poses = data["poses"]
    xs = [p["x"] for p in poses.values()] + [
        p["prior"]["x"] for p in poses.values() if p.get("prior")
    ]
    ys = [p["y"] for p in poses.values()] + [
        p["prior"]["y"] for p in poses.values() if p.get("prior")
    ]
    pad = 25.0
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    scale = width / (x1 - x0)
    height = int((y1 - y0) * scale)
    image = Image.new("RGB", (width, height), (247, 246, 242))
    draw = ImageDraw.Draw(image)
    font = label_font(12)

    def px(x: float, y: float) -> tuple[float, float]:
        return (x - x0) * scale, (y1 - y) * scale

    for b in ctx.buildings:
        if b.outline[:, 0].max() < x0 or b.outline[:, 0].min() > x1:
            continue
        if b.outline[:, 1].max() < y0 or b.outline[:, 1].min() > y1:
            continue
        fill = (238, 222, 170) if b.campus else (225, 225, 225)
        draw.polygon(
            [px(x, y) for x, y in b.outline], fill=fill, outline=(120, 120, 120)
        )
        cx, cy = b.outline.mean(axis=0)
        draw.text(px(cx, cy), b.code, fill=(70, 70, 70), font=font, anchor="mm")
    for scene, p in poses.items():
        x, y = px(p["x"], p["y"])
        if p.get("prior"):
            draw.line(
                [px(p["prior"]["x"], p["prior"]["y"]), (x, y)],
                fill=(150, 150, 150),
                width=1,
            )
        a, b, azimuth = p["ellipse"]
        _ellipse(draw, (x, y), a * 5 * scale, b * 5 * scale, azimuth)
        colour = (210, 30, 40) if p.get("sightings") else (90, 90, 200)
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=colour)
        h = math.radians(p["heading_deg"])
        draw.line(
            [(x, y), (x + 9 * math.sin(h), y - 9 * math.cos(h))], fill=colour, width=2
        )
        draw.text((x + 4, y - 12), scene.removeprefix("scene_"), fill=colour, font=font)
    for name, lm in data["landmarks"].items():
        x, y = px(lm["x"], lm["y"])
        tie = lm["source"] == "tie"
        draw.regular_polygon((x, y, 4), 3 if tie else 4, fill=(20, 140, 60))
        if tie:
            draw.text((x + 4, y + 2), name, fill=(20, 110, 50), font=label_font(10))
    bar = 10 * scale
    draw.line([(12, height - 14), (12 + bar, height - 14)], fill=(0, 0, 0), width=4)
    draw.text((12, height - 32), "10 m   (ellipses x5)", fill=(0, 0, 0), font=font)
    return image


def _ellipse(
    draw: ImageDraw.ImageDraw,
    centre: tuple[float, float],
    a: float,
    b: float,
    azimuth_deg: float,
) -> None:
    t = math.radians(azimuth_deg)
    points = []
    for k in range(37):
        u = 2 * math.pi * k / 36
        ex, ey = a * math.cos(u), b * math.sin(u)
        # Major axis along the compass azimuth (screen y grows downwards).
        dx = ex * math.sin(t) + ey * math.cos(t)
        dy = -(ex * math.cos(t) - ey * math.sin(t))
        points.append((centre[0] + dx, centre[1] + dy))
    draw.line(points, fill=(230, 120, 40), width=1)


def write_report(ctx: LookContext, data: Mapping[str, Any], out_dir: Path) -> Path:
    img_dir = out_dir / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    tripod = float(data.get("tripod_m", 1.6))
    overview_map(ctx, data).save(img_dir / "overview.png")
    sightings: dict[str, list[tuple[str, float]]] = {}
    worst: dict[str, float] = {}
    for r in data["residuals"]:
        if r["kind"] == "landmark":
            sightings.setdefault(r["scene"], []).append((r["target"], r["ath_deg"]))
            worst[r["scene"]] = max(worst.get(r["scene"], 0.0), abs(r["residual_deg"]))
    checks = acceptance(data)
    rows: list[str] = []
    sections: list[str] = []
    poses = data["poses"]
    for scene in sorted(poses, key=lambda s: -poses[s]["shift_m"]):
        p = poses[scene]
        label = html.escape(ctx.label(scene))
        a, b, _ = p["ellipse"]
        kind = "free" if p["free"] else (p.get("model") or "-")
        rows.append(
            f"<tr><td>{scene}</td><td>{label}</td><td>{kind}</td>"
            f"<td>{p.get('sightings', 0)}</td><td>{p['shift_m']:.1f}</td>"
            f"<td>{p['turn_deg']:+.1f}</td><td>{a:.2f} &times; {b:.2f}</td>"
            f"<td>{worst.get(scene, 0.0):.2f}</td></tr>"
        )
        marks = sightings.get(scene)
        if not marks or p.get("prior") is None:
            continue
        before = _pose(p["prior"] | {"z": p.get("z", tripod)}, scene, tripod)
        after = _pose(p, scene, tripod)
        evidence_strip(ctx, scene, before, marks).save(
            img_dir / f"{scene}_before.jpg", quality=82
        )
        evidence_strip(ctx, scene, after, marks).save(
            img_dir / f"{scene}_after.jpg", quality=82
        )
        sections.append(
            f"<section><h3>{scene} · {label}</h3>"
            f"<p>moved {p['shift_m']:.1f} m, turned {p['turn_deg']:+.1f}°, "
            f"1&sigma; {a:.2f} &times; {b:.2f} m, {len(marks)} sightings "
            f"(green lines), worst residual {worst.get(scene, 0.0):.2f}°</p>"
            f"<p class=k>before</p><img src='img/{scene}_before.jpg'>"
            f"<p class=k>after</p><img src='img/{scene}_after.jpg'></section>"
        )
    badge = {True: "pass", False: "fail", None: "n/a"}
    check_rows = "".join(
        f"<tr><td>{html.escape(c.name)}</td><td>{c.value}</td>"
        f"<td class={badge[c.ok]}>{badge[c.ok]}</td></tr>"
        for c in checks
    )
    page = f"""<!doctype html><html><head><meta charset=utf-8>
<title>Survey evidence</title><style>{CSS}</style></head><body>
<h1>Panorama survey — evidence</h1>
<p>Generated {html.escape(str(data.get("generated_at", "")))} · tripod {tripod} m</p>
<h2>Acceptance</h2><table>{check_rows}</table>
<h2>Overview</h2><img src='img/overview.png'>
<h2>Panoramas</h2><table><tr><th>scene</th><th>label</th><th>model</th><th>sightings</th>
<th>moved m</th><th>turned °</th><th>1&sigma; ellipse m</th>
<th>worst residual °</th></tr>
{"".join(rows)}</table>
<h2>Evidence</h2>{"".join(sections)}
</body></html>"""
    index = out_dir / "index.html"
    index.write_text(page, "utf-8")
    return index
