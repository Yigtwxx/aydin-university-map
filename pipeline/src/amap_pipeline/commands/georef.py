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
    interior_raster,
    level,
    outline_score_raster,
    search,
    umeyama_2d,
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
SCALE_FACTORS = (0.35, 0.42, 0.5, 0.58, 0.67, 0.77, 0.88, 1.0, 1.15, 1.3)
# Around a scale prior from tour spacing, which is far tighter than the
# tripod-height prior.
LINK_SCALE_FACTORS = (0.8, 0.88, 0.95, 1.0, 1.06, 1.13, 1.25)
CELL_M = 1.0
MIN_SHARED_SCENES = 3


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


def georef_path(workspace: Path, model: int) -> Path:
    return workspace / f"georef_m{model}.json"


@app.command("run")
def georef_run(
    run: Annotated[str, typer.Option(help="SfM run name under data/recon/.")],
    model: Annotated[
        int | None, typer.Option(help="Model index (default: every model).")
    ] = None,
    min_frames: Annotated[
        int, typer.Option(help="Skip models with fewer panoramas.")
    ] = 3,
    align_to: Annotated[
        str | None,
        typer.Option(
            help="Georeferenced run whose poses fix models that share >= 3 scenes."
        ),
    ] = None,
    link_scale_m: Annotated[
        float | None,
        typer.Option(
            help="Median tour-link length in metres; sets the scale prior "
            "(the verified campus model has 6.2 m)."
        ),
    ] = None,
    tour_window_m: Annotated[
        float | None,
        typer.Option(
            help="Search within this radius of the scenes' tour coordinates "
            "(only when they are specific, not the campus-wide point)."
        ),
    ] = None,
) -> None:
    """Level each model, search yaw/scale/shift against OSM, refine with ICP.

    Every model gets its own ``georef_m<N>.json``; ``amap graph export`` merges
    them and keeps the best-fitting pose per scene.
    """
    workspace = paths.recon_dir() / run
    sfm_report = json.loads((workspace / "report.json").read_text("utf-8"))
    models = [
        m["model"]
        for m in sfm_report["models"]
        if (model is None and m["reg_frames"] >= min_frames) or m["model"] == model
    ]
    if not models:
        typer.echo("no model to georeference")
        raise typer.Exit(code=1)
    reference: dict[str, dict[str, Any]] = {}
    if align_to:
        from amap_pipeline.commands.graph import georef_files, merge_poses

        reference = merge_poses(
            [
                json.loads(p.read_text("utf-8"))
                for p in georef_files(paths.recon_dir() / align_to)
            ]
        )
    for index in models:
        typer.echo(f"--- model {index}")
        try:
            georef_model(
                run,
                workspace,
                index,
                reference=reference,
                reference_run=align_to,
                link_scale_m=link_scale_m,
                tour_window_m=tour_window_m,
            )
        except typer.Exit:
            typer.echo(f"model {index}: skipped")


def median_link_units(cams: np.ndarray, links: list[tuple[int, int]]) -> float | None:
    lengths = [float(np.linalg.norm(cams[a] - cams[b])) for a, b in links]
    return float(np.median(lengths)) if lengths else None


def tour_centre(
    order: list[str], scenes: dict[str, Any], projector: LocalProjector
) -> tuple[float, float] | None:
    """Mean tour coordinate of the model's scenes, if they are specific.

    The tour gives one coordinate per building or area; scenes labelled with
    the campus-wide point (the map origin) carry no position information.
    """
    xy = [
        projector.to_local(scenes[s]["lng"], scenes[s]["lat"])
        for s in order
        if scenes[s].get("lat") is not None
    ]
    if not xy:
        return None
    centre = np.mean(np.array(xy), axis=0)
    if float(np.hypot(*centre)) < 25.0:
        return None
    return float(centre[0]), float(centre[1])


def georef_model(
    run: str,
    workspace: Path,
    model_index: int,
    reference: dict[str, dict[str, Any]] | None = None,
    reference_run: str | None = None,
    link_scale_m: float | None = None,
    tour_window_m: float | None = None,
) -> None:
    import pycolmap

    rec = pycolmap.Reconstruction(workspace / "sparse" / str(model_index))
    poses = extract_poses(rec)
    down, level_dev = gravity(poses)
    prior = metric_scale(poses, down)
    points = np.array([p.xyz for p in rec.points3D.values()])
    levelled = level(poses, points, down)
    cams = levelled.camera_xy()
    order = list(levelled.cameras)
    scenes_meta = {
        s["name"]: s
        for s in json.loads((paths.derived_dir() / "scenes.json").read_text("utf-8"))
    }
    link_units = median_link_units(cams, walking_links(order, scenes_meta))
    if link_scale_m is not None and link_units:
        # Tour spacing is a steadier scale cue than the tripod height.
        prior_mpu = link_scale_m / link_units
    elif prior is not None:
        prior_mpu = prior.metres_per_unit
    else:
        typer.echo("no metric scale prior (not enough ground points)")
        raise typer.Exit(code=1)
    walls = wall_points(levelled, prior_mpu)

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
        f"{len(poses)} panos, {len(walls)} wall points, scale prior {prior_mpu:.3f} m/u"
    )

    shrunk = footprints.buffer(-0.75)
    shared = [i for i, sc in enumerate(order) if reference and sc in reference]
    method = "osm_search"
    scale_prior = prior_mpu
    scale_factors: tuple[float, ...] = SCALE_FACTORS
    if link_scale_m is not None and link_units:
        scale_factors = LINK_SCALE_FACTORS
        method = "osm_search_link_scale"
    centre = (0.0, 0.0)
    window = SEARCH_RADIUS_M
    if tour_window_m is not None and (
        found := tour_centre(order, scenes_meta, projector)
    ):
        centre, window = found, tour_window_m
        typer.echo(f"search window {window:.0f} m around tour point {centre}")

    candidates: list[Candidate] = []
    if reference and len(shared) >= MIN_SHARED_SCENES:
        # Sim(2) from shared scenes to their trusted map positions.
        target = np.array(
            [[reference[order[i]]["x"], reference[order[i]]["y"]] for i in shared]
        )
        init = umeyama_2d(cams[shared], target)
        residual = np.linalg.norm(init.apply(cams[shared]) - target, axis=1)
        typer.echo(
            f"aligned to {reference_run} on {len(shared)} shared scenes, "
            f"residual median {float(np.median(residual)):.2f} m"
        )
        method = f"aligned:{reference_run}"
        icp = icp_refine(walls, outline, init, iterations=0)
        checked = constrain(
            Candidate(init, 1.0), cams, footprints, shrunk, anchors, links
        )
        refined: list[tuple[Candidate, IcpResult]] = [(checked, icp)]
    else:
        candidates = search(
            walls,
            cams,
            score_map,
            footprints,
            scale_prior,
            centre_window_m=window,
            centre_xy=centre,
            anchors=anchors,
            links=links,
            interior=interior_raster(footprints, score_map),
            scale_factors=scale_factors,
        )
        refined = []
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
    scale_ratio = best.transform.scale / prior_mpu

    # Ground level from the final (OSM) scale; the tripod prior is biased.
    ground_z = (
        float(np.median([c[2] for c in levelled.cameras.values()]))
        - TRIPOD_HEIGHT_M / best.transform.scale
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
        "method": method,
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
    georef_path(workspace, model_index).write_text(
        json.dumps(result, indent=2) + "\n", "utf-8"
    )
    _overlay(
        paths.data_dir() / "debug" / f"{run}_m{model_index}_georef.png",
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
        f"cameras inside buildings: {len(inside)}  -> "
        f"{georef_path(workspace, model_index)}"
    )
