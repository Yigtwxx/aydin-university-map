"""``amap survey``: measure where the panoramas stand and prove it."""

import json
import math
import statistics
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from shapely.geometry import Polygon

from amap_contracts.geo import CAMPUS_ORIGIN_LAT, CAMPUS_ORIGIN_LNG
from amap_contracts.graph import Graph
from amap_pipeline import paths
from amap_pipeline.commands.graph import georef_files, merge_poses, trusted
from amap_pipeline.geo.osm import LocalProjector
from amap_pipeline.geo.overrides import apply_pose_overrides, load_pose_overrides
from amap_pipeline.look.camera import DEFAULT_TRIPOD_M
from amap_pipeline.look.context import load_context, parse_buildings
from amap_pipeline.survey.kroki import place, ransac, read_markers
from amap_pipeline.survey.observations import Survey, load_survey
from amap_pipeline.survey.report import acceptance, write_report
from amap_pipeline.survey.solve import PriorPose, TourLink, holdout, solve_survey
from amap_pipeline.survey.triage import PosedScene, build_triage, render_markdown

app = typer.Typer(help="Panorama survey commands.", no_args_is_help=True)

# The tour's campus-wide fallback coordinate (279 scenes share it).
TOUR_DEFAULT_LATLNG = (40.991470, 28.797111)


def scene_models(run_dir: Path) -> dict[str, str]:
    """Scene -> the trusted model it takes its pose from (lowest ICP RMS)."""
    best: dict[str, tuple[float, str]] = {}
    for path in georef_files(run_dir):
        georef = json.loads(path.read_text("utf-8"))
        if not trusted(georef):
            continue
        model = f"m{georef.get('model', path.stem.removeprefix('georef_m'))}"
        rms = float(georef["quality"]["icp_rms_m"])
        for scene in georef["scenes"]:
            if scene not in best or rms < best[scene][0]:
                best[scene] = (rms, model)
    return {scene: model for scene, (_, model) in best.items()}


def posed_scenes(graph: Graph, models: dict[str, str]) -> dict[str, PosedScene]:
    return {
        n.id: PosedScene(
            id=n.id,
            kind=n.kind.value,
            x=n.enu[0],
            y=n.enu[1],
            heading_deg=n.heading_deg,
            pose_source=n.pose_source.value,
            label=n.label.tr,
            area=n.area.tr,
            model=models.get(n.id),
        )
        for n in graph.nodes
    }


def campus_outlines(buildings_json: Path) -> list[tuple[str, Polygon]]:
    data = json.loads(buildings_json.read_text("utf-8"))
    return [
        (str(b["id"]), Polygon(b["outline"]))
        for b in data["buildings"]
        if len(b["outline"]) >= 3
    ]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


@app.command("triage")
def survey_triage(
    run: Annotated[str, typer.Option(help="Georeferenced SfM run.")] = "outdoor96_lg",
) -> None:
    """Rank the panoramas worth a look: data/debug/survey/triage.{json,md}."""
    out_dir = paths.data_dir() / "out"
    graph = Graph.from_geojson(
        json.loads((out_dir / "graph.geojson").read_text("utf-8"))
    )
    scenes: list[dict[str, Any]] = json.loads(
        (paths.derived_dir() / "scenes.json").read_text("utf-8")
    )
    report = json.loads((out_dir / "graph_report.json").read_text("utf-8"))
    projector = LocalProjector()
    posed = posed_scenes(graph, scene_models(paths.recon_dir() / run))
    coarse = {s["name"]: projector.to_local(s["lng"], s["lat"]) for s in scenes}
    default_xy = projector.to_local(TOUR_DEFAULT_LATLNG[1], TOUR_DEFAULT_LATLNG[0])
    triage = build_triage(
        posed,
        scenes,
        coarse,
        default_xy,
        campus_outlines(out_dir / "buildings.json"),
        read_jsonl(paths.data_dir() / "rag" / "vision.jsonl"),
        skip_links=[frozenset(j.split("|")) for j in report.get("menu_jumps", [])],
    )
    debug = paths.data_dir() / "debug" / "survey"
    debug.mkdir(parents=True, exist_ok=True)
    payload = {
        "run": run,
        "origin": [CAMPUS_ORIGIN_LAT, CAMPUS_ORIGIN_LNG],
        **triage.to_json(),
    }
    (debug / "triage.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )
    labels = {s["name"]: s["label"]["tr"] for s in scenes}
    outdoor = frozenset(s["name"] for s in scenes if s["kind"] != "indoor")
    (debug / "triage.md").write_text(
        render_markdown(triage, posed, labels, outdoor=outdoor), "utf-8"
    )
    flagged = sum(1 for s in triage.scenes if s.verdict != "ok")
    typer.echo(
        f"{len(triage.links)} arrows, {flagged} scenes flagged, "
        f"{len(triage.inside)} inside footprints, {len(triage.unposed)} unposed"
    )
    typer.echo(f"wrote {debug / 'triage.md'}")


def base_poses(run: str) -> dict[str, dict[str, Any]]:
    """Poses before the survey: trusted SfM models plus the hand overrides."""
    run_dir = paths.recon_dir() / run
    georefs = [json.loads(p.read_text("utf-8")) for p in georef_files(run_dir)]
    posed = merge_poses(georefs)
    return apply_pose_overrides(posed, load_pose_overrides(), LocalProjector())


def survey_inputs(
    run: str, scenes: list[dict[str, Any]], survey: Survey
) -> tuple[dict[str, PriorPose], list[TourLink], dict[str, float]]:
    """Priors for outdoor panoramas and entrances, tour links, camera heights."""
    kinds = {s["name"]: s["kind"] for s in scenes}
    models = scene_models(paths.recon_dir() / run)
    priors: dict[str, PriorPose] = {}
    heights: dict[str, float] = {}
    for scene, record in base_poses(run).items():
        if kinds.get(scene, "indoor") == "indoor":
            continue
        priors[scene] = PriorPose(
            scene=scene,
            x=float(record["x"]),
            y=float(record["y"]),
            heading_deg=float(record["heading_deg"]) % 360.0,
            model=models.get(scene),
            source=str(record.get("pose_source", "sfm")),
        )
        heights[scene] = float(record["height_m"])
    for scene, notes in survey.scenes.items():
        if scene in heights or notes.init is None:
            continue
        x, y, _ = notes.init
        nearest = min(
            priors.values(), key=lambda p: math.hypot(p.x - x, p.y - y), default=None
        )
        heights[scene] = heights[nearest.scene] if nearest else DEFAULT_TRIPOD_M
    links = [
        TourLink(s["name"], target, float(ath))
        for s in scenes
        for target, ath in s.get("link_yaw", {}).items()
    ]
    return priors, links, heights


@app.command("solve")
def survey_solve(
    run: Annotated[str, typer.Option(help="Georeferenced SfM run.")] = "outdoor96_lg",
    with_holdout: Annotated[
        bool, typer.Option("--holdout", help="Cross-validate the sightings.")
    ] = False,
    notebook: Annotated[
        list[Path] | None,
        typer.Option(
            help="Notebook file or folder, repeatable (default: configs/survey)."
        ),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help="Write here (default: data/derived/survey.json)."),
    ] = None,
) -> None:
    """Adjust poses and landmarks to the sightings: data/derived/survey.json."""
    ctx_buildings = parse_buildings(
        json.loads((paths.data_dir() / "out" / "buildings.json").read_text("utf-8"))
    )
    survey = (
        load_survey(ctx_buildings)
        if not notebook
        else load_survey(ctx_buildings, notebook)
    )
    scenes: list[dict[str, Any]] = json.loads(
        (paths.derived_dir() / "scenes.json").read_text("utf-8")
    )
    priors, links, heights = survey_inputs(run, scenes, survey)
    solution = solve_survey(priors, links, survey)
    old_map = {s: (float(r["x"]), float(r["y"])) for s, r in base_poses(run).items()}
    sightings: dict[str, int] = {
        scene: len(notes.sightings) for scene, notes in survey.scenes.items()
    }
    landmark_res = [r for r in solution.residuals if r.kind == "landmark"]
    hotspot_res = [r for r in solution.residuals if r.kind == "hotspot"]
    summary: dict[str, Any] = {
        "scenes": len(solution.poses),
        "landmarks": len(solution.landmarks),
        "sightings": len(landmark_res),
        "rms_sighting_deg": _rms([r.residual_deg for r in landmark_res]),
        "median_hotspot_deg": _median_abs([r.residual_deg for r in hotspot_res]),
        "success": solution.success,
    }
    holdout_deg: list[float] = []
    if with_holdout:
        holdout_deg = holdout(priors, links, survey)
        summary["holdout_median_deg"] = _median_abs(holdout_deg)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "run": run,
        "tripod_m": survey.tripod_m,
        "summary": summary,
        "models": {m: asdict(e) for m, e in solution.models.items()},
        "poses": {
            scene: {
                **asdict(p),
                "z": heights.get(scene, DEFAULT_TRIPOD_M),
                "sightings": sightings.get(scene, 0),
                "map_shift_m": (
                    round(
                        math.hypot(p.x - old_map[scene][0], p.y - old_map[scene][1]), 2
                    )
                    if scene in old_map
                    else None
                ),
                "prior": asdict(priors[scene]) if scene in priors else None,
            }
            for scene, p in solution.poses.items()
        },
        "landmarks": {n: asdict(lm) for n, lm in solution.landmarks.items()},
        "residuals": [asdict(r) for r in solution.residuals],
        "holdout_deg": holdout_deg,
    }
    out = out or paths.derived_dir() / "survey.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", "utf-8")
    typer.echo(json.dumps(summary, ensure_ascii=False))
    for warning in solution.warnings:
        typer.echo(f"warning: {warning}")
    moved = sorted(
        (p for p in solution.poses.values() if sightings.get(p.scene)),
        key=lambda p: -p.shift_m,
    )
    for p in moved[:15]:
        typer.echo(
            f"  {p.scene}: moved {p.shift_m:5.1f} m, turned {p.turn_deg:+6.1f}°, "
            f"1 sigma {p.ellipse[0]:.2f} x {p.ellipse[1]:.2f} m"
        )
    typer.echo(f"wrote {out}")


def _rms(values: list[float]) -> float | None:
    return (
        round(math.sqrt(sum(v * v for v in values) / len(values)), 3)
        if values
        else None
    )


def _median_abs(values: list[float]) -> float | None:
    return round(statistics.median(abs(v) for v in values), 3) if values else None


@app.command("residuals")
def survey_residuals(
    scene: Annotated[
        list[str] | None, typer.Option("--scene", help="Only these scenes.")
    ] = None,
    worst: Annotated[int, typer.Option(help="Show the N largest.")] = 30,
    kind: Annotated[
        str | None, typer.Option(help="Only 'landmark' or 'hotspot' rows.")
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option(help="Solve output (default: data/derived/survey.json)."),
    ] = None,
) -> None:
    """Sightings and arrows the last solve could not satisfy (from survey.json)."""
    source = file or paths.derived_dir() / "survey.json"
    data = json.loads(source.read_text("utf-8"))
    wanted = {s if s.startswith("scene_") else f"scene_{s}" for s in scene or []}
    rows = [
        r
        for r in data["residuals"]
        if (not wanted or r["scene"] in wanted or r["target"] in wanted)
        and (kind is None or r["kind"] == kind)
    ]
    rows.sort(key=lambda r: -abs(r["residual_deg"]) / r["sigma_deg"])
    for r in rows[:worst]:
        typer.echo(
            f"{r['scene']} -> {r['target']:<24} {r['kind']:<8} ath {r['ath_deg']:6.1f} "
            f"residual {r['residual_deg']:+7.2f} deg (sigma {r['sigma_deg']}, "
            f"weight {r['weight']:.2f})"
        )
    for name, lm in sorted(data["landmarks"].items()):
        seen = [r for r in rows if r["target"] == name]
        if wanted and not seen:
            continue
        shift = "" if lm["shift_m"] is None else f", {lm['shift_m']:.1f} m from prior"
        typer.echo(
            f"landmark {name}: x {lm['x']:.1f} y {lm['y']:.1f} "
            f"(1-sigma {lm['sigma_x']:.2f}/{lm['sigma_y']:.2f} m{shift})"
        )
    for s in sorted(wanted):
        pose = data["poses"].get(s)
        if pose:
            typer.echo(
                f"{s}: x {pose['x']:.1f} y {pose['y']:.1f} heading "
                f"{pose['heading_deg']:.1f}, moved {pose['shift_m']:.1f} m, "
                f"turned {pose['turn_deg']:+.1f}, 1-sigma ellipse "
                f"{pose['ellipse'][0]:.2f} x {pose['ellipse'][1]:.2f} m"
            )


@app.command("report")
def survey_report(
    file: Annotated[
        Path | None,
        typer.Option(help="Solve output (default: data/derived/survey.json)."),
    ] = None,
) -> None:
    """Evidence page: data/debug/survey/index.html (before/after overlays, ellipses)."""
    source = file or paths.derived_dir() / "survey.json"
    data = json.loads(source.read_text("utf-8"))
    ctx = load_context(paths.data_dir(), tripod_m=float(data.get("tripod_m", 1.6)))
    index = write_report(ctx, data, paths.data_dir() / "debug" / "survey")
    for check in acceptance(data):
        status = {True: "pass", False: "FAIL", None: "n/a"}[check.ok]
        typer.echo(f"{status:>4}  {check.name}: {check.value}")
    typer.echo(f"wrote {index}")


@app.command("kroki")
def survey_kroki(
    file: Annotated[
        Path | None,
        typer.Option(help="Solve output whose sighted poses anchor the sketch."),
    ] = None,
    threshold: Annotated[float, typer.Option(help="RANSAC inlier distance, m.")] = 5.0,
    graph_poses: Annotated[
        bool, typer.Option("--graph", help="Anchor on graph poses instead (biased).")
    ] = False,
) -> None:
    """Fit the tour's campus sketch to measured poses; place the rest from it."""
    views = read_markers(paths.data_dir() / "raw" / "kroki_markers.json")
    known: dict[str, tuple[float, float]] = {}
    if graph_poses:
        graph = Graph.from_geojson(
            json.loads((paths.data_dir() / "out" / "graph.geojson").read_text("utf-8"))
        )
        known = {
            n.id: (n.enu[0], n.enu[1])
            for n in graph.nodes
            if n.pose_source.value in ("sfm", "manual", "surveyed")
        }
    else:
        data = json.loads(
            (file or paths.derived_dir() / "survey.json").read_text("utf-8")
        )
        # Only poses the pictures measured: a free pose with no sightings is
        # just its hand-set prior.
        known = {
            s: (p["x"], p["y"]) for s, p in data["poses"].items() if p.get("sightings")
        }
    report: dict[str, Any] = {}
    for name, markers in views.items():
        try:
            # "üstten görünüş" is the top-view inset, a plan; the other is a render.
            fit = ransac(markers, known, plan="ustten" in name, threshold_m=threshold)
        except ValueError as exc:
            typer.echo(f"{name}: {exc}")
            continue
        placed = place(fit, markers)
        typer.echo(
            f"{name}: {len(fit.inliers)} inliers of {len(fit.residuals)} known, "
            f"scatter {fit.scatter_m} m"
        )
        for scene, (x, y) in sorted(placed.items()):
            res = fit.residuals.get(scene)
            status = (
                "new"
                if res is None
                else ("inlier" if scene in fit.inliers else "OUTLIER")
            )
            extra = "" if res is None else f" ({res} m from its pose)"
            typer.echo(
                f"  {scene}: sketch puts it at {x:7.1f} {y:7.1f}  {status}{extra}"
            )
        report[name] = {
            "inliers": fit.inliers,
            "residuals": fit.residuals,
            "scatter_m": fit.scatter_m,
            "placed": placed,
        }
    out = paths.derived_dir() / "kroki.json"
    out.write_text(json.dumps(report, indent=1) + "\n", "utf-8")
    typer.echo(f"wrote {out}")
