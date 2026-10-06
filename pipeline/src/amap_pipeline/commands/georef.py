"""``amap georef``: place an SfM model on the map using OSM building footprints."""

import json
import math
import re
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import typer
from PIL import Image, ImageDraw
from shapely.geometry import Point

from amap_pipeline import paths
from amap_pipeline.geo.align import (
    Anchor,
    Candidate,
    IcpResult,
    constrain,
    footprint_union,
    icp_refine,
    level,
    outline_score_raster,
    search,
    wall_points,
)
from amap_pipeline.geo.osm import (
    CAMPUS_OSM_BBOX,
    Building,
    LocalProjector,
    fetch_buildings_raw,
    parse_buildings,
    sample_outlines,
)
from amap_pipeline.recon.evaluate import (
    TRIPOD_HEIGHT_M,
    extract_poses,
    gravity,
    metric_scale,
)

app = typer.Typer(help="Georeferencing commands.", no_args_is_help=True)

SEARCH_RADIUS_M = 350.0
CELL_M = 1.0


_ENTRANCE_RE = re.compile(r"^([A-Z]) Blok Giri")
_OSM_BLOCK_RE = re.compile(r"Aydın Üniversitesi ([A-Z]) Binası")


def entrance_anchors(
    order: list[str], scenes: dict[str, Any], buildings: list[Building]
) -> tuple[list[Anchor], list[str]]:
    """Entrance scenes whose block letter matches a named OSM building."""
    blocks: dict[str, Building] = {}
    for b in buildings:
        match = _OSM_BLOCK_RE.search(b.name or "")
        if match:
            blocks[match.group(1)] = b
    anchors: list[Anchor] = []
    names: list[str] = []
    for index, scene in enumerate(order):
        match = _ENTRANCE_RE.match(scenes[scene]["label"]["tr"])
        if match and match.group(1) in blocks:
            anchors.append(Anchor(index, blocks[match.group(1)].outline))
            names.append(f"{scene}:{match.group(1)}")
    return anchors, names


def walking_links(order: list[str], scenes: dict[str, Any]) -> list[tuple[int, int]]:
    index = {s: i for i, s in enumerate(order)}
    pairs = {
        (min(index[a], index[b]), max(index[a], index[b]))
        for a in order
        for b in scenes[a]["links"]
        if b in index
    }
    return sorted(pairs)


def anchor_report(
    anchors: list[Anchor], names: list[str], best: IcpResult, cams: np.ndarray
) -> dict[str, float]:
    moved = best.transform.apply(cams)
    return {
        name: round(float(a.target.boundary.distance(Point(*moved[a.camera]))), 2)
        for a, name in zip(anchors, names, strict=True)
    }


def _yaw_gap_deg(a: Candidate, b: Candidate) -> float:
    return abs((math.degrees(a.transform.yaw - b.transform.yaw) + 180) % 360 - 180)


def _overlay(
    path: Path,
    buildings: list[Building],
    walls_map: np.ndarray,
    cams_map: dict[str, np.ndarray],
    centre: np.ndarray,
    half: float = 180.0,
    px: int = 1400,
) -> None:
    def to_px(x: float, y: float) -> tuple[float, float]:
        return (
            (x - centre[0] + half) / (2 * half) * px,
            (centre[1] + half - y) / (2 * half) * px,
        )

    img = Image.new("RGB", (px, px), (252, 252, 250))
    draw = ImageDraw.Draw(img)
    for b in buildings:
        draw.polygon(
            [to_px(x, y) for x, y in b.outline.exterior.coords],
            outline=(120, 120, 120),
            fill=(228, 228, 224),
        )
    for x, y in walls_map[:: max(1, len(walls_map) // 6000)]:
        u, v = to_px(float(x), float(y))
        draw.point((u, v), fill=(235, 120, 30))
    for xy in cams_map.values():
        u, v = to_px(float(xy[0]), float(xy[1]))
        draw.ellipse((u - 4, v - 4, u + 4, v + 4), fill=(25, 85, 200))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


@app.command("run")
def georef_run(
    run: Annotated[str, typer.Option(help="SfM run name under data/recon/.")],
    model: Annotated[
        int | None, typer.Option(help="Model index (default: largest).")
    ] = None,
) -> None:
    """Gravity-level the model, search yaw/scale/shift against OSM, refine with ICP."""
    import pycolmap

    workspace = paths.recon_dir() / run
    sfm_report = json.loads((workspace / "report.json").read_text("utf-8"))
    model_index = model if model is not None else sfm_report["models"][0]["model"]
    rec = pycolmap.Reconstruction(workspace / "sparse" / str(model_index))
    poses = extract_poses(rec)
    down, level_dev = gravity(poses)
    prior = metric_scale(poses, down)
    if prior is None:
        typer.echo("no metric scale prior (not enough ground points)")
        raise typer.Exit(code=1)
    points = np.array([p.xyz for p in rec.points3D.values()])
    levelled = level(poses, points, down)
    walls = wall_points(levelled, prior.metres_per_unit)
    cams = levelled.camera_xy()
    order = list(levelled.cameras)
    scenes_meta = {
        s["name"]: s
        for s in json.loads((paths.derived_dir() / "scenes.json").read_text("utf-8"))
    }

    projector = LocalProjector()
    buildings = parse_buildings(
        fetch_buildings_raw(
            CAMPUS_OSM_BBOX, paths.data_dir() / "osm" / "buildings.json"
        ),
        projector,
    )
    outline = sample_outlines(buildings)
    r = SEARCH_RADIUS_M + 150.0
    score_map = outline_score_raster(outline, (-r, -r, r, r), CELL_M)
    footprints = footprint_union([b.outline for b in buildings])
    anchors, anchor_names = entrance_anchors(order, scenes_meta, buildings)
    links = walking_links(order, scenes_meta)
    typer.echo(f"anchors: {anchor_names}")
    typer.echo(
        f"{len(poses)} panos, {len(walls)} wall points, "
        f"scale prior {prior.metres_per_unit:.3f} m/u"
    )

    candidates = search(
        walls,
        cams,
        score_map,
        footprints,
        prior.metres_per_unit,
        centre_window_m=SEARCH_RADIUS_M,
        anchors=anchors,
        links=links,
    )
    shrunk = footprints.buffer(-0.75)
    refined: list[tuple[Candidate, IcpResult]] = []
    for cand in candidates[:4]:
        icp = icp_refine(walls, outline, cand.transform)
        checked = constrain(
            Candidate(icp.transform, cand.score),
            cams,
            footprints,
            shrunk,
            anchors,
            links,
        )
        refined.append((checked, icp))
    refined.sort(key=lambda cr: -cr[0].rank_value * cr[1].inlier_ratio)
    best_cand, best = refined[0]
    rivals = [c for c in candidates if _yaw_gap_deg(c, best_cand) > 15]
    margin = best_cand.rank_value / rivals[0].rank_value if rivals else math.inf

    cams_map = {
        s: best.transform.apply(c[None, :2])[0] for s, c in levelled.cameras.items()
    }
    walls_map = best.transform.apply(walls)
    inside = [
        s
        for s, xy in cams_map.items()
        if footprints.contains(Point(float(xy[0]), float(xy[1])))
    ]
    scale_ratio = best.transform.scale / prior.metres_per_unit

    ground_z = (
        float(np.median([c[2] for c in levelled.cameras.values()]))
        - TRIPOD_HEIGHT_M / prior.metres_per_unit
    )
    scenes: dict[str, Any] = {}
    for pose in poses:
        front = levelled.basis @ pose.rig_from_world[2]
        heading_xy = (
            best.transform.apply(front[None, :2])[0]
            - best.transform.apply(np.zeros((1, 2)))[0]
        )
        bearing = math.degrees(math.atan2(heading_xy[0], heading_xy[1])) % 360.0
        x, y = cams_map[pose.scene]
        lng, lat = projector.to_wgs84(float(x), float(y))
        alt = (levelled.cameras[pose.scene][2] - ground_z) * best.transform.scale
        scenes[pose.scene] = {
            "lat": lat,
            "lng": lng,
            "x": float(x),
            "y": float(y),
            "height_m": float(alt),
            "heading_deg": bearing,
        }

    result = {
        "run": run,
        "model": model_index,
        "levelling_deg": round(level_dev, 2),
        "basis_levelled_from_model": levelled.basis.tolist(),
        "similarity": {
            "yaw_deg": math.degrees(best.transform.yaw),
            "scale_m_per_unit": best.transform.scale,
            "shift_m": list(best.transform.shift),
        },
        "ground_z_model": ground_z,
        "quality": {
            "icp_rms_m": round(best.rms_m, 3),
            "inlier_ratio": round(best.inlier_ratio, 3),
            "coarse_score": round(best_cand.score, 4),
            "margin_vs_other_yaw": round(margin, 3),
            "scale_vs_camera_height_prior": round(scale_ratio, 3),
            "cameras_inside_buildings": inside,
            "links_crossing_buildings": round(best_cand.links_crossing, 3),
            "anchor_distance_m": anchor_report(anchors, anchor_names, best, cams),
        },
        "scenes": scenes,
    }
    (workspace / "georef.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    _overlay(
        paths.data_dir() / "debug" / f"{run}_georef.png",
        buildings,
        walls_map,
        cams_map,
        np.mean(list(cams_map.values()), axis=0),
    )

    typer.echo(
        f"yaw {math.degrees(best.transform.yaw):.1f} deg, "
        f"scale {best.transform.scale:.3f} m/u ({scale_ratio:.2f}x prior)"
    )
    typer.echo(
        f"ICP rms {best.rms_m:.2f} m, inliers {best.inlier_ratio:.1%}, "
        f"margin vs other yaw {margin:.2f}"
    )
    typer.echo(
        f"cameras inside buildings: {len(inside)}  -> {workspace / 'georef.json'}"
    )
