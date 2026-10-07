"""``amap furniture``: find street furniture in the panoramas and place it."""

import math
import time
from pathlib import Path
from typing import Annotated, Any

import typer

from amap_pipeline import paths
from amap_pipeline.look.render import FaceCache

app = typer.Typer(help="Street furniture commands.", no_args_is_help=True)

DETECTIONS = "detections.jsonl"


@app.command("detect")
def furniture_detect(
    scene_set: Annotated[
        str, typer.Option("--set", help="Scene set in data/derived/sets.")
    ] = "outdoor_all",
    threshold: Annotated[float, typer.Option(help="Detector score threshold.")] = 0.18,
    limit: Annotated[int, typer.Option(help="Stop after N scenes (0 = all).")] = 0,
) -> None:
    """OWLv2 over every panorama of a set -> data/derived/detections.jsonl.

    Resumable: scenes already in the file are skipped. Needs the `detect`
    extra (torch + transformers); heavy, run it on the workstation.
    """
    from amap_pipeline.furniture.detect import (
        Detector,
        detect_scene,
        read_detections,
        write_detections,
    )

    scenes = (paths.sets_dir() / f"{scene_set}.txt").read_text("utf-8").split()
    out = paths.derived_dir() / DETECTIONS
    done = {d["scene"] for d in read_detections(out)} | _empty_scenes(out)
    todo = [s for s in scenes if s not in done]
    if limit:
        todo = todo[:limit]
    typer.echo(f"{len(todo)} scenes to look at ({len(done)} done)")
    detector = Detector(threshold=threshold)
    typer.echo(f"device: {detector.device}")
    faces = FaceCache([paths.tiles_dir(), paths.data_dir() / "out" / "panos"], 2)
    start = time.time()
    for i, scene in enumerate(todo, 1):
        found = detect_scene(detector, faces.faces(scene), scene)
        if found:
            write_detections(out, found)
        else:
            _mark_empty(out, scene)
        rate = (time.time() - start) / i
        typer.echo(
            f"[{i}/{len(todo)}] {scene}: {len(found)} boxes "
            f"({rate:.1f} s/scene, ~{rate * (len(todo) - i) / 60:.0f} min left)"
        )


def _empty_path(out: Path) -> Path:
    return out.with_suffix(".empty.txt")


def _empty_scenes(out: Path) -> set[str]:
    path = _empty_path(out)
    return set(path.read_text("utf-8").split()) if path.is_file() else set()


def _mark_empty(out: Path, scene: str) -> None:
    with _empty_path(out).open("a", encoding="utf-8") as fh:
        fh.write(scene + "\n")


@app.command("locate")
def furniture_locate(
    poses_file: Annotated[
        Path | None,
        typer.Option("--poses", help="Solve output whose poses to use (else graph)."),
    ] = None,
    tripod: Annotated[float, typer.Option(help="Camera height for monoplot.")] = 1.6,
) -> None:
    """Detections -> furniture candidates (data/derived/furniture_candidates.json)."""
    import json
    from dataclasses import asdict

    from amap_pipeline.furniture.detect import read_detections
    from amap_pipeline.furniture.locate import cluster, place, tripod_height
    from amap_pipeline.look.context import load_context

    ctx = load_context(paths.data_dir(), tripod_m=tripod, survey_poses=poses_file)
    measured = {
        s: p
        for s, p in ctx.poses.items()
        if ctx.pose_sources.get(s) in ("surveyed", "sfm", "manual")
    }
    detections = read_detections(paths.derived_dir() / DETECTIONS)
    placed = place(detections, measured)
    candidates = cluster(placed, measured)
    height = tripod_height(candidates, measured)
    out = paths.derived_dir() / "furniture_candidates.json"
    out.write_text(
        json.dumps(
            {
                "tripod_m_used": tripod,
                "tripod_m_measured": height,
                "headings": {s: p.heading_deg for s, p in measured.items()},
                "candidates": [
                    {
                        **{k: v for k, v in asdict(c).items() if k != "members"},
                        "members": [asdict(m) for m in c.members],
                    }
                    for c in candidates
                ],
            },
            indent=1,
        )
        + "\n",
        "utf-8",
    )
    by_kind: dict[str, int] = {}
    for c in candidates:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
    typer.echo(
        f"{len(detections)} detections, {len(placed)} placed, "
        f"{len(candidates)} candidates"
    )
    typer.echo(f"by kind: {dict(sorted(by_kind.items()))}")
    typer.echo(f"tripod height measured by triangulated objects: {height} m")
    typer.echo(f"wrote {out}")


@app.command("sheets")
def furniture_sheets(
    per_sheet: Annotated[int, typer.Option(help="Candidates per sheet.")] = 12,
) -> None:
    """Review sheets: one crop per candidate from its nearest panorama
    (data/debug/furniture/<kind>_<n>.png), numbered like the candidates file."""
    import json

    from PIL import Image, ImageDraw

    from amap_pipeline.look.render import View, render_view
    from amap_pipeline.recon.evaluate import label_font

    data = json.loads(
        (paths.derived_dir() / "furniture_candidates.json").read_text("utf-8")
    )
    faces = FaceCache([paths.tiles_dir(), paths.data_dir() / "out" / "panos"], 4)
    out = paths.data_dir() / "debug" / "furniture"
    out.mkdir(parents=True, exist_ok=True)
    font = label_font(16)
    cell = 360
    by_kind: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for i, c in enumerate(data["candidates"]):
        by_kind.setdefault(str(c["kind"]), []).append((i, c))
    written = 0
    for kind, items in sorted(by_kind.items()):
        for start in range(0, len(items), per_sheet):
            chunk = items[start : start + per_sheet]
            cols = 4
            rows = (len(chunk) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * cell, rows * cell), (20, 20, 20))
            for k, (index, c) in enumerate(chunk):
                members: list[dict[str, Any]] = c["members"]
                near = min(members, key=lambda m: float(m["range_m"]))
                pose_scene = str(near["scene"])
                # Centre on the detection: bearing back to the panorama's ath.
                data_pose = faces.faces(pose_scene)
                ath = _ath_of(pose_scene, float(near["bearing_deg"]))
                # About 5 m across at the object's range.
                rng = max(float(near["range_m"]), 1.0)
                fov = max(12.0, min(70.0, 2.0 * math.degrees(math.atan(2.5 / rng))))
                view = View(ath, float(near["atv_deg"]) - 4.0, fov, cell, cell)
                tile = Image.fromarray(render_view(data_pose, view))
                draw = ImageDraw.Draw(tile)
                label = (
                    f"#{index} {kind} {c['method'][:3]} "
                    f"{len(c['scenes'])}v s{float(c['score']):.2f}"
                )
                draw.text((6, 6), label, fill=(255, 255, 0), font=font,
                          stroke_width=2, stroke_fill=(0, 0, 0))  # fmt: skip
                draw.line([(cell / 2, cell / 2 - 14), (cell / 2, cell / 2 + 14)],
                          fill=(255, 0, 0), width=2)  # fmt: skip
                sheet.paste(tile, ((k % cols) * cell, (k // cols) * cell))
            name = out / f"{kind}_{start // per_sheet:02d}.png"
            sheet.save(name)
            written += 1
    typer.echo(f"wrote {written} sheets to {out}")


_POSES_CACHE: dict[str, float] = {}


def _ath_of(scene: str, bearing: float) -> float:
    """ath in ``scene`` of a compass bearing, using the poses locate used."""
    heading = _POSES_CACHE.get(scene)
    if heading is None:
        import json

        data = json.loads(
            (paths.derived_dir() / "furniture_candidates.json").read_text("utf-8")
        )
        for name, h in data.get("headings", {}).items():
            _POSES_CACHE[name] = float(h)
        heading = _POSES_CACHE.get(scene, 0.0)
    return (bearing - heading) % 360.0
