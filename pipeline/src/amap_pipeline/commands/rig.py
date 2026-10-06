"""``amap rig``: verify the cube-face rig convention on real panoramas (gate G1)."""

import json
import statistics
from collections import Counter
from typing import Annotated

import typer

from amap_pipeline import paths
from amap_pipeline.acquire.sink import read_scene_set
from amap_pipeline.acquire.store import TileError
from amap_pipeline.recon.cubemap import (
    FACES,
    fit_transforms,
    load_faces,
    write_rig_config,
)

app = typer.Typer(help="Cube-face rig commands.", no_args_is_help=True)

CANONICAL_FACE_PX = 1300
MAX_MEDIAN_SEAM_RATIO = 2.5


@app.command("seam-test")
def seam_test(
    set_name: Annotated[str, typer.Option("--set", help="Scene set name.")],
    sample: Annotated[int, typer.Option(help="Scenes to test (evenly spaced).")] = 12,
) -> None:
    """Fit per-face image transforms from seam continuity and write the rig config."""
    try:
        scenes = read_scene_set(paths.sets_dir(), set_name)
    except TileError as exc:
        raise typer.BadParameter(str(exc)) from exc
    step = max(1, len(scenes) // max(sample, 1))
    picked = scenes[::step][:sample]

    votes: dict[str, Counter[str]] = {face: Counter() for face in FACES}
    edge_ratios: dict[str, list[float]] = {}
    per_scene: dict[str, dict[str, object]] = {}
    for scene in picked:
        result = fit_transforms(load_faces(paths.tiles_dir() / scene))
        for face, name in result.transforms.items():
            votes[face][name] += 1
        for edge, ratio in result.edge_errors.items():
            edge_ratios.setdefault(edge, []).append(ratio)
        per_scene[scene] = {
            "transforms": result.transforms,
            "max_seam_ratio": round(max(result.edge_errors.values()), 3),
        }
        typer.echo(
            f"{scene}: {result.transforms} "
            f"max seam ratio {max(result.edge_errors.values()):.2f}"
        )

    chosen = {face: votes[face].most_common(1)[0][0] for face in FACES}
    consistent = all(len(votes[face]) == 1 for face in FACES)
    medians = {edge: statistics.median(v) for edge, v in edge_ratios.items()}
    worst_median = max(medians.values())
    passed = consistent and worst_median <= MAX_MEDIAN_SEAM_RATIO

    report = {
        "set": set_name,
        "scenes_tested": picked,
        "votes": {face: dict(c) for face, c in votes.items()},
        "chosen": chosen,
        "consistent": consistent,
        "median_seam_ratio": {e: round(m, 3) for e, m in sorted(medians.items())},
        "gate_g1_passed": passed,
        "per_scene": per_scene,
    }
    out_dir = paths.recon_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "seam_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    typer.echo(f"chosen transforms: {chosen}  consistent={consistent}")
    typer.echo(f"worst median seam ratio: {worst_median:.2f}")
    if not passed:
        typer.echo("G1 FAILED: see data/recon/seam_report.json")
        raise typer.Exit(code=1)
    write_rig_config(out_dir / "rig_config.json", CANONICAL_FACE_PX, chosen)
    typer.echo(f"G1 passed -> wrote {out_dir / 'rig_config.json'}")
