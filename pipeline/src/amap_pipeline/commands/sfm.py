"""``amap sfm``: sparse reconstruction of a scene set (Phase 1 spike and beyond)."""

import json
import math
import statistics
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer

from amap_pipeline import paths
from amap_pipeline.acquire.sink import read_scene_set
from amap_pipeline.recon.evaluate import (
    edge_lengths_m,
    extract_poses,
    gravity,
    metric_scale,
    p28_consistency,
    plot_topdown,
    yaw_deg,
)
from amap_pipeline.recon.sfm import SfmConfig, run_sfm
from amap_pipeline.tour import load_dump, load_overrides
from amap_pipeline.tour.export import classify_tour

app = typer.Typer(help="Structure-from-Motion commands.", no_args_is_help=True)


@app.command("run")
def sfm_run(
    config: Annotated[Path, typer.Option(help="SfM TOML config.")],
    map_only: Annotated[
        bool, typer.Option(help="Reuse features/matches, only re-run the mapper.")
    ] = False,
) -> None:
    """Stage faces, extract/match SIFT on tour-link pairs and map the rig."""
    transforms_file = paths.recon_dir() / "face_transforms.json"
    if not transforms_file.is_file():
        raise typer.BadParameter("run `amap rig seam-test` first (gate G1)")
    cfg = replace(
        SfmConfig.from_toml(config),
        transforms=json.loads(transforms_file.read_text("utf-8")),
    )
    scenes = read_scene_set(paths.sets_dir(), cfg.set)
    tour = classify_tour(
        load_dump(paths.raw_dump()),
        load_overrides(paths.derived_dir() / "scene_overrides.toml"),
    )
    workspace = paths.recon_dir() / cfg.run
    report = run_sfm(
        cfg, scenes, tour.adjacency, paths.tiles_dir(), workspace, map_only=map_only
    )
    for model in report["models"][:5]:
        typer.echo(
            f"model {model['model']}: {model['reg_frames']} frames, "
            f"{len(model['scenes_all_faces'])} full panos, {model['points3D']} points, "
            f"reproj {model['mean_reproj_px']} px, track {model['mean_track_length']}"
        )
    typer.echo(f"timings (s): {report['seconds']}")
    typer.echo(f"report: {workspace / 'report.json'}")


@app.command("report")
def sfm_report(
    run: Annotated[str, typer.Option(help="Run name under data/recon/.")],
    max_edge_m: Annotated[float, typer.Option(help="Flag longer tour links.")] = 60.0,
) -> None:
    """Evaluate the largest model: gravity, metric scale, link lengths, headings."""
    import pycolmap

    workspace = paths.recon_dir() / run
    sfm = json.loads((workspace / "report.json").read_text("utf-8"))
    largest = sfm["models"][0]
    rec = pycolmap.Reconstruction(workspace / "sparse" / str(largest["model"]))
    poses = extract_poses(rec)
    down, level_dev = gravity(poses)
    scale = metric_scale(poses, down)
    if scale is None:
        typer.echo("not enough ground points to estimate the metric scale")
        raise typer.Exit(code=1)

    scenes = {
        s["name"]: s
        for s in json.loads((paths.derived_dir() / "scenes.json").read_text("utf-8"))
    }
    registered = {p.scene for p in poses}
    edges = sorted(
        {
            (min(a, b), max(a, b))
            for a in registered
            for b in scenes[a]["links"]
            if b in registered
        }
    )
    lengths = edge_lengths_m(poses, edges, scale.metres_per_unit)
    long_links = {
        f"{a}|{b}": round(d, 1) for (a, b), d in lengths.items() if d > max_edge_m
    }
    yaws = {p.scene: yaw_deg(p, down) for p in poses}
    p28 = {
        s: float(scenes[s]["angle_p28"])
        for s in registered
        if scenes[s]["angle_p28"] is not None
    }
    heading = p28_consistency(yaws, p28)

    set_size = sfm["scenes"]
    full = len(largest["scenes_all_faces"])
    median_edge = statistics.median(lengths.values()) if lengths else 0.0
    gates = {
        "G2_registered": f"{full}/{set_size}",
        "G2_pass": full >= math.ceil(0.9 * set_size),
        "G3_pass": largest["mean_reproj_px"] <= 1.5
        and largest["mean_track_length"] >= 3,
        "G4_height_cv": round(scale.cv, 3),
        "G4_median_edge_m": round(median_edge, 2),
        "G4_pass_partial": scale.cv <= 0.15 and 3 <= median_edge <= 25,
        "G4_footprint_check": "pending georeference (phase 2)",
        "G5_runtime_s": round(sum(sfm["seconds"].values()), 1),
        "G5_pass": sum(sfm["seconds"].values()) <= 7200,
    }
    evaluation = {
        "run": run,
        "model": largest["model"],
        "levelling_median_deviation_deg": round(level_dev, 2),
        "metres_per_unit": round(scale.metres_per_unit, 5),
        "camera_height_units": {k: round(v, 4) for k, v in scale.heights_units.items()},
        "edge_lengths_m": {f"{a}|{b}": round(d, 2) for (a, b), d in lengths.items()},
        "long_links_m": long_links,
        "p28_heading": None
        if heading is None
        else {
            "sign": heading.sign,
            "offset_deg": round(heading.offset_deg, 2),
            "median_abs_residual_deg": round(heading.median_abs_residual_deg, 2),
        },
        "gates": gates,
    }
    (workspace / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2) + "\n", "utf-8"
    )
    labels = {s: scenes[s]["label"]["tr"] for s in registered}
    png = paths.data_dir() / "debug" / f"{run}_topdown.png"
    plot_topdown(poses, edges, down, scale.metres_per_unit, labels, png)

    typer.echo(f"levelling: median deviation {level_dev:.2f} deg")
    typer.echo(
        f"scale: {scale.metres_per_unit:.4f} m/unit, camera height CV {scale.cv:.1%}"
    )
    typer.echo(f"links: {len(lengths)} measured, median {median_edge:.1f} m")
    typer.echo(f"links longer than {max_edge_m:.0f} m: {long_links}")
    if heading is not None:
        typer.echo(
            f"p28 vs SfM yaw: sign {heading.sign:+d}, "
            f"offset {heading.offset_deg:.1f} deg, "
            f"median residual {heading.median_abs_residual_deg:.1f} deg"
        )
    typer.echo(f"gates: {gates}")
    typer.echo(f"top-down plot: {png}")
