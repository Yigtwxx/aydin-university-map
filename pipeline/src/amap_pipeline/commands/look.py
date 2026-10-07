"""``amap look``: walk the tour from the local panoramas and draw the map into it.

Every picture lands in ``data/debug/look/`` next to a JSON sidecar with the
exact parameters, so any piece of evidence can be regenerated. Nothing here is
published: ``amap publish`` only ships ``data/out``.
"""

import json
import math
import os
from collections import deque
from dataclasses import asdict, replace
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import typer
from PIL import Image

from amap_pipeline import paths
from amap_pipeline.look.camera import DEFAULT_TRIPOD_M, Pose, bearing_to_ath
from amap_pipeline.look.context import LookContext, load_context
from amap_pipeline.look.edges import snap_edge
from amap_pipeline.look.overlay import Mark as TieMark
from amap_pipeline.look.overlay import (
    Painter,
    StripCanvas,
    ViewCanvas,
    draw_ath_marks,
    draw_buildings,
    draw_grid,
    draw_hotspots,
    draw_marks,
    draw_nodes,
)
from amap_pipeline.look.plan import render_plan
from amap_pipeline.look.render import Strip, View, render_strip, render_view
from amap_pipeline.look.sample import sample_colour
from amap_pipeline.survey.ortho import Grid, agreement, blend, project_ground

app = typer.Typer(help="Panorama views with the map drawn in.", no_args_is_help=True)

ALL_LAYERS = "grid,buildings,nodes,hotspots"

Scene = Annotated[str, typer.Option("--scene", help="Scene id, e.g. scene_428563.")]
Tripod = Annotated[float, typer.Option(help="Camera height above its ground, metres.")]
PoseOpt = Annotated[
    str | None, typer.Option("--pose", help="Try a pose instead: 'x,y,heading[,z]'.")
]
Layers = Annotated[str, typer.Option(help="Comma-separated overlay layers.")]
Mark = Annotated[
    list[str] | None,
    typer.Option("--mark", help="Vertical marker 'label=ath' (repeatable)."),
]


def _scene_id(scene: str) -> str:
    return scene if scene.startswith("scene_") else f"scene_{scene}"


def _context(tripod: float) -> LookContext:
    # AMAP_SURVEY_POSES=<solve output>: draw from the survey's measured poses.
    survey = os.environ.get("AMAP_SURVEY_POSES")
    return load_context(
        paths.data_dir(),
        tripod_m=tripod,
        survey_poses=Path(survey) if survey else None,
    )


def _pose(ctx: LookContext, scene: str, override: str | None) -> Pose | None:
    base = ctx.pose(scene)
    if override is None:
        if base is not None and ctx.pose_sources.get(scene) == "interpolated":
            typer.echo(f"{scene}: interpolated pose, map overlays are unreliable")
        return base
    parts = [float(v) for v in override.split(",")]
    if len(parts) not in (3, 4):
        raise typer.BadParameter("--pose takes 'x,y,heading[,z]'")
    z = parts[3] if len(parts) == 4 else (base.z if base else 1.6)
    tripod = base.tripod_m if base else DEFAULT_TRIPOD_M
    return Pose(
        scene=scene,
        x=parts[0],
        y=parts[1],
        z=z,
        heading_deg=parts[2] % 360.0,
        tripod_m=tripod,
    )


def _marks(marks: list[str] | None) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for m in marks or []:
        label, _, value = m.rpartition("=")
        out.append((label or value, float(value)))
    return out


def _paint(
    painter: Painter,
    ctx: LookContext,
    scene: str,
    pose: Pose | None,
    layers: str,
    marks: list[tuple[str, float]],
    grid_step: float = 5.0,
) -> None:
    """Layers: grid, buildings (= outlines + corners), outlines, corners, nodes,
    hotspots, ties (solved landmarks, with AMAP_SURVEY_POSES)."""
    wanted = {layer.strip() for layer in layers.split(",") if layer.strip()}
    if "buildings" in wanted:
        wanted |= {"outlines", "corners"}
    if "grid" in wanted:
        draw_grid(
            painter,
            pose,
            step_deg=grid_step,
            label_every=1 if grid_step <= 1.0 else 2,
            label_atv_deg=-8.0 if grid_step <= 1.0 else -30.0,
        )
    if pose is not None and wanted & {"outlines", "corners"}:
        draw_buildings(
            painter,
            ctx,
            pose,
            outlines="outlines" in wanted,
            corners="corners" in wanted,
        )
    if pose is not None and "nodes" in wanted:
        draw_nodes(painter, ctx, pose)
    if "hotspots" in wanted:
        draw_hotspots(painter, ctx, scene)
    if pose is not None and "ties" in wanted:
        ties = ctx.extra.get("landmarks", {})
        near = [
            TieMark(name, x, y)
            for name, (x, y) in ties.items()
            if math.hypot(x - pose.x, y - pose.y) < 70.0
        ]
        draw_marks(painter, pose, near)
    draw_ath_marks(painter, marks)


def _out_dir(scene: str) -> Path:
    path = paths.data_dir() / "debug" / "look" / scene
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save(image: Image.Image, path: Path, params: dict[str, Any]) -> None:
    image.save(path)
    path.with_suffix(".json").write_text(
        json.dumps(params, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )
    typer.echo(f"wrote {path}")


def _pose_params(pose: Pose | None) -> dict[str, Any] | None:
    return None if pose is None else asdict(pose)


def view_image(
    ctx: LookContext,
    scene: str,
    pose: Pose | None,
    view: View,
    layers: str,
    marks: list[tuple[str, float]],
    grid_step: float = 5.0,
) -> Image.Image:
    painter = Painter(render_view(ctx.faces.faces(scene), view), ViewCanvas(view))
    _paint(painter, ctx, scene, pose, layers, marks, grid_step)
    return painter.result()


def strip_image(
    ctx: LookContext,
    scene: str,
    pose: Pose | None,
    strip: Strip,
    layers: str,
    marks: list[tuple[str, float]],
    grid_step: float = 5.0,
) -> Image.Image:
    painter = Painter(render_strip(ctx.faces.faces(scene), strip), StripCanvas(strip))
    _paint(painter, ctx, scene, pose, layers, marks, grid_step)
    return painter.result()


@app.command("view")
def look_view(
    scene: Scene,
    ath: Annotated[float | None, typer.Option(help="Centre, rig degrees.")] = None,
    bearing: Annotated[
        float | None, typer.Option(help="Centre as a compass bearing (uses the pose).")
    ] = None,
    pitch: Annotated[float, typer.Option(help="Degrees below the horizon.")] = 0.0,
    fov: Annotated[float, typer.Option(help="Horizontal field of view.")] = 90.0,
    width: int = 1280,
    height: int = 800,
    layers: Layers = ALL_LAYERS,
    mark: Mark = None,
    grid_step: Annotated[float, typer.Option(help="Grid spacing, degrees.")] = 5.0,
    tripod: Tripod = DEFAULT_TRIPOD_M,
    pose: PoseOpt = None,
) -> None:
    """A rectilinear view in one direction."""
    scene = _scene_id(scene)
    ctx = _context(tripod)
    p = _pose(ctx, scene, pose)
    if bearing is not None:
        if p is None:
            raise typer.BadParameter(f"{scene} has no pose; use --ath")
        ath = bearing_to_ath(p, bearing)
    centre = 0.0 if ath is None else ath
    view = View(centre, pitch, fov, width, height)
    image = view_image(ctx, scene, p, view, layers, _marks(mark), grid_step)
    name = f"view_{centre:05.1f}_{pitch:+.0f}_{fov:.0f}.png"
    _save(
        image,
        _out_dir(scene) / name,
        {
            "scene": scene,
            "view": asdict(view),
            "pose": _pose_params(p),
            "layers": layers,
            "marks": mark or [],
        },
    )


@app.command("strip")
def look_strip(
    scene: Scene,
    start: Annotated[float, typer.Option(help="First ath of the strip.")] = 0.0,
    span: Annotated[float, typer.Option(help="Degrees of ath covered.")] = 360.0,
    top: Annotated[float, typer.Option(help="Top atv (negative = up).")] = -35.0,
    bottom: Annotated[float, typer.Option(help="Bottom atv.")] = 35.0,
    px_per_deg: float = 6.0,
    layers: Layers = ALL_LAYERS,
    mark: Mark = None,
    grid_step: Annotated[float, typer.Option(help="Grid spacing, degrees.")] = 5.0,
    tripod: Tripod = DEFAULT_TRIPOD_M,
    pose: PoseOpt = None,
) -> None:
    """An equirectangular band with the compass ruler."""
    scene = _scene_id(scene)
    ctx = _context(tripod)
    p = _pose(ctx, scene, pose)
    strip = Strip(start, span, top, bottom, px_per_deg)
    image = strip_image(ctx, scene, p, strip, layers, _marks(mark), grid_step)
    _save(
        image,
        _out_dir(scene) / f"strip_{start:05.1f}_{span:.0f}.png",
        {
            "scene": scene,
            "strip": asdict(strip),
            "pose": _pose_params(p),
            "layers": layers,
        },
    )


@app.command("plan")
def look_plan(
    scene: Scene,
    radius: Annotated[float, typer.Option(help="Metres around the camera.")] = 70.0,
    ray: Mark = None,
    tripod: Tripod = DEFAULT_TRIPOD_M,
    pose: PoseOpt = None,
) -> None:
    """The map around the camera, with optional bearing rays 'label=ath'."""
    scene = _scene_id(scene)
    ctx = _context(tripod)
    p = _pose(ctx, scene, pose)
    if p is None:
        raise typer.BadParameter(f"{scene} has no pose; pass --pose")
    image = render_plan(ctx, p, radius_m=radius, rays=_marks(ray))
    _save(
        image,
        _out_dir(scene) / "plan.png",
        {"scene": scene, "pose": _pose_params(p), "radius_m": radius},
    )


@app.command("sheet")
def look_sheet(
    scene: Scene,
    px_per_deg: float = 8.0,
    layers: Layers = ALL_LAYERS,
    mark: Mark = None,
    tripod: Tripod = DEFAULT_TRIPOD_M,
    pose: PoseOpt = None,
    radius: Annotated[float, typer.Option(help="Plan radius, metres.")] = 70.0,
) -> None:
    """The whole panorama as two half strips plus the plan: one scene at a glance."""
    scene = _scene_id(scene)
    ctx = _context(tripod)
    p = _pose(ctx, scene, pose)
    marks = _marks(mark)
    halves = [
        strip_image(
            ctx, scene, p, Strip(s, 180.0, -35.0, 35.0, px_per_deg), layers, marks
        )
        for s in (0.0, 180.0)
    ]
    sheet = Image.new("RGB", (halves[0].width, halves[0].height * 2 + 6), (0, 0, 0))
    sheet.paste(halves[0], (0, 0))
    sheet.paste(halves[1], (0, halves[0].height + 6))
    out = _out_dir(scene)
    params = {"scene": scene, "pose": _pose_params(p), "layers": layers}
    _save(sheet, out / "sheet.png", {**params, "px_per_deg": px_per_deg})
    if p is not None:
        plan = render_plan(ctx, p, radius_m=radius, rays=marks)
        _save(plan, out / "plan.png", {**params, "radius_m": radius})


@app.command("snap")
def look_snap(
    scene: Scene,
    ath: Annotated[list[float], typer.Option(help="Rough ath (repeatable).")],
    window: Annotated[float, typer.Option(help="Search ±degrees.")] = 1.5,
    top: float = -25.0,
    bottom: float = 10.0,
) -> None:
    """Snap rough bearings to the nearest vertical edge (sub-degree)."""
    scene = _scene_id(scene)
    ctx = _context(DEFAULT_TRIPOD_M)
    faces = ctx.faces.faces(scene)
    for rough in ath:
        s = snap_edge(
            faces, rough, window_deg=window, atv_top_deg=top, atv_bottom_deg=bottom
        )
        flag = "clear" if s.clear else "weak"
        typer.echo(
            f"{rough:7.2f} -> {s.ath_deg:7.2f} (shift {s.shift_deg:+.2f}, "
            f"contrast {s.contrast:.1f}, {flag})"
        )


@app.command("sample")
def look_sample(
    scene: Scene,
    ath: Annotated[float, typer.Option(help="Patch centre ath.")],
    atv: Annotated[float, typer.Option(help="Patch centre atv.")],
    radius: Annotated[float, typer.Option(help="Patch half-size, degrees.")] = 1.0,
) -> None:
    """Median colour of a patch (hex, OKLab)."""
    scene = _scene_id(scene)
    ctx = _context(DEFAULT_TRIPOD_M)
    c = sample_colour(ctx.faces.faces(scene), ath, atv, radius_deg=radius)
    lab = ", ".join(f"{v:.3f}" for v in c.oklab)
    typer.echo(f"{c.hex}  oklab({lab})  spread {c.spread:.1f}")


def tour_path(
    link_yaw: dict[str, dict[str, float]], start: str, goal: str
) -> list[str]:
    """Fewest-links path through the tour's arrows (either direction)."""
    neighbours: dict[str, set[str]] = {}
    for a, targets in link_yaw.items():
        for b in targets:
            neighbours.setdefault(a, set()).add(b)
            neighbours.setdefault(b, set()).add(a)
    previous: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            break
        for nxt in sorted(neighbours.get(node, ())):
            if nxt not in previous:
                previous[nxt] = node
                queue.append(nxt)
    if goal not in previous:
        raise typer.BadParameter(f"no tour path from {start} to {goal}")
    path: list[str] = []
    node: str | None = goal
    while node is not None:
        path.append(node)
        node = previous[node]
    return path[::-1]


@app.command("walk")
def look_walk(
    scene: Scene,
    to: Annotated[str, typer.Option("--to", help="Walk to this scene.")],
    fov: float = 100.0,
    layers: Layers = ALL_LAYERS,
    tripod: Tripod = DEFAULT_TRIPOD_M,
) -> None:
    """Views along the tour, each facing the arrow to the next panorama."""
    start, goal = _scene_id(scene), _scene_id(to)
    ctx = _context(tripod)
    path = tour_path(ctx.link_yaw, start, goal)
    out = paths.data_dir() / "debug" / "look" / f"walk_{start}_{goal}"
    out.mkdir(parents=True, exist_ok=True)
    for i, (here, nxt) in enumerate(pairwise(path)):
        ath = ctx.link_yaw.get(here, {}).get(nxt)
        if ath is None:
            # Only the reverse arrow exists: face away from where it points.
            back = ctx.link_yaw.get(nxt, {}).get(here)
            ath = 0.0 if back is None else _reverse_guess(ctx, here, nxt, back)
        view = View(ath, 5.0, fov, 1280, 800)
        image = view_image(ctx, here, ctx.pose(here), view, layers, [])
        _save(
            image,
            out / f"{i:02d}_{here}.png",
            {
                "scene": here,
                "next": nxt,
                "view": asdict(view),
                "pose": _pose_params(ctx.pose(here)),
            },
        )
    typer.echo(" -> ".join(f"{s} ({ctx.label(s)})" for s in path))


def _reverse_guess(ctx: LookContext, here: str, there: str, back_ath: float) -> float:
    """ath at ``here`` towards ``there`` when only ``there`` has the arrow."""
    a, b = ctx.pose(here), ctx.pose(there)
    if a is None or b is None:
        return 0.0
    bearing = (back_ath + b.heading_deg + 180.0) % 360.0
    return bearing_to_ath(a, bearing)


@app.command("near")
def look_near(
    scene: Scene,
    radius: Annotated[float, typer.Option(help="Metres around the camera.")] = 60.0,
    tripod: Tripod = DEFAULT_TRIPOD_M,
    pose: PoseOpt = None,
) -> None:
    """Text list: nearby panoramas (where the map says they are) and tour arrows."""
    scene = _scene_id(scene)
    ctx = _context(tripod)
    p = _pose(ctx, scene, pose)
    arrows = ctx.link_yaw.get(scene, {})
    typer.echo(f"{scene} {ctx.label(scene)} [{ctx.pose_sources.get(scene, 'no pose')}]")
    if p is None:
        for target, ath in sorted(arrows.items(), key=lambda kv: kv[1]):
            typer.echo(f"  arrow ath {ath:6.1f} -> {target} {ctx.label(target)}")
        return
    typer.echo(f"  pose x {p.x:.1f} y {p.y:.1f} heading {p.heading_deg:.1f}")
    rows: list[tuple[float, str]] = []
    for other, q in ctx.poses.items():
        if other == scene or ctx.pose_sources.get(other) == "interpolated":
            continue
        dx, dy = q.x - p.x, q.y - p.y
        dist = math.hypot(dx, dy)
        if dist > radius:
            continue
        bearing = math.degrees(math.atan2(dx, dy)) % 360.0
        ath = bearing_to_ath(p, bearing)
        arrow = arrows.get(other)
        tour = f"  arrow ath {arrow:6.1f}" if arrow is not None else ""
        rows.append(
            (
                ath,
                f"  map ath {ath:6.1f} (B{bearing:5.1f}) {dist:5.1f} m  "
                f"{other} {ctx.label(other)[:28]} [{ctx.pose_sources.get(other)}]"
                f"{tour}",
            )
        )
    for _, line in sorted(rows):
        typer.echo(line)
    for target, ath in sorted(arrows.items(), key=lambda kv: kv[1]):
        q = ctx.pose(target)
        if q is None or ctx.pose_sources.get(target) == "interpolated":
            typer.echo(
                f"  arrow ath {ath:6.1f} -> {target} {ctx.label(target)} (no pose)"
            )


def _bbox(text: str) -> tuple[float, float, float, float]:
    parts = [float(v) for v in text.split(",")]
    if len(parts) != 4:
        raise typer.BadParameter("--bbox takes 'x0,y0,x1,y1' in local metres")
    x0, y0, x1, y1 = parts
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


@app.command("ortho")
def look_ortho(
    bbox: Annotated[str, typer.Option(help="'x0,y0,x1,y1' local metres.")],
    res: Annotated[float, typer.Option(help="Metres per pixel.")] = 0.05,
    tripod: Tripod = DEFAULT_TRIPOD_M,
    scene: Annotated[
        list[str] | None, typer.Option("--scene", help="Only these panoramas.")
    ] = None,
    max_range: Annotated[
        float, typer.Option(help="Ground radius per panorama.")
    ] = 14.0,
    scan_tripod: Annotated[
        str | None,
        typer.Option(help="'lo:hi:step': score tripod heights by overlap agreement."),
    ] = None,
) -> None:
    """Ground orthomosaic of the measured panoramas over a box (data/debug/ortho)."""
    x0, y0, x1, y1 = _bbox(bbox)
    grid = Grid(x0, y0, x1, y1, res)
    ctx = _context(tripod)
    wanted = {_scene_id(s) for s in scene or []}
    poses = [
        p
        for s, p in ctx.poses.items()
        if (not wanted or s in wanted)
        and ctx.pose_sources.get(s) != "interpolated"
        and x0 - max_range <= p.x <= x1 + max_range
        and y0 - max_range <= p.y <= y1 + max_range
    ]
    if not poses:
        raise typer.BadParameter("no measured panorama near that box")
    if scan_tripod:
        lo, hi, step = (float(v) for v in scan_tripod.split(":"))
        for height in np.arange(lo, hi + 1e-9, step):
            layers = [
                project_ground(
                    ctx.faces.faces(p.scene),
                    replace(p, tripod_m=float(height)),
                    grid,
                    max_range_m=max_range,
                )
                for p in poses
            ]
            scores = [
                s
                for i, a in enumerate(layers)
                for b in layers[i + 1 :]
                if (s := agreement(a, b)) is not None
            ]
            mean = sum(scores) / len(scores) if scores else float("nan")
            typer.echo(
                f"tripod {height:.2f} m: agreement {mean:.3f} ({len(scores)} pairs)"
            )
        return
    layers = [
        project_ground(ctx.faces.faces(p.scene), p, grid, max_range_m=max_range)
        for p in poses
    ]
    image = Image.fromarray(blend(layers, grid))
    out = paths.data_dir() / "debug" / "ortho"
    out.mkdir(parents=True, exist_ok=True)
    name = f"ortho_{x0:.0f}_{y0:.0f}_{x1:.0f}_{y1:.0f}"
    _save(
        image,
        out / f"{name}.png",
        {
            "bbox": [x0, y0, x1, y1],
            "res_m": res,
            "tripod_m": tripod,
            "scenes": [p.scene for p in poses],
        },
    )
