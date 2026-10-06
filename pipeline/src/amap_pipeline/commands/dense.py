"""``amap dense``: textured campus mesh (OpenMVS) and SfM building heights."""

import json
import logging
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import typer
from shapely.geometry import Polygon

from amap_pipeline import paths
from amap_pipeline.geo.sfm_heights import HeightParams, building_heights
from amap_pipeline.recon.dense import (
    STAGES,
    DenseConfig,
    DenseRunner,
    Tools,
    model_to_enu,
)
from amap_pipeline.recon.meshio import FloatArray, read_ply

app = typer.Typer(help="Dense mesh commands.", no_args_is_help=True)


def _georef(workspace: Path, model: int) -> dict[str, Any]:
    path = workspace / f"georef_m{model}.json"
    if not path.is_file():
        raise typer.BadParameter(f"model {model} has no georeference ({path})")
    return json.loads(path.read_text("utf-8"))


def _logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command("run")
def dense_run(
    run: Annotated[str, typer.Option(help="SfM run name under data/recon/.")],
    model: Annotated[int, typer.Option(help="Georeferenced model index.")],
    resolution_level: Annotated[
        int, typer.Option(help="DensifyPointCloud --resolution-level.")
    ] = 2,
    number_views: Annotated[
        int, typer.Option(help="DensifyPointCloud --number-views (0: all).")
    ] = 5,
    fusion_depth_diff: Annotated[
        float, typer.Option(help="DensifyPointCloud --fusion-depth-diff-threshold.")
    ] = 0.01,
    min_image_observations: Annotated[
        int, typer.Option(help="Drop cube faces with fewer sparse points.")
    ] = 10,
    max_support_m: Annotated[
        float, typer.Option(help="Drop mesh faces farther from the dense cloud.")
    ] = 1.0,
    refine: Annotated[bool, typer.Option(help="Run RefineMesh.")] = True,
    refine_resolution_level: Annotated[
        int, typer.Option(help="RefineMesh --resolution-level.")
    ] = 2,
    refine_decimate: Annotated[
        float, typer.Option(help="RefineMesh --decimate (0 auto, 1 keep all faces).")
    ] = 0.0,
    crop_margin_m: Annotated[
        float, typer.Option(help="Keep the mesh this far beyond the cameras' bbox.")
    ] = 120.0,
    max_tile_faces: Annotated[
        int, typer.Option(help="Quadtree split threshold (faces per tile).")
    ] = 400_000,
    max_texture_px: Annotated[
        int, typer.Option(help="TextureMesh --max-texture-size.")
    ] = 8192,
    timeout_h: Annotated[float, typer.Option(help="Timeout per tool call.")] = 3.0,
    until: Annotated[
        str | None, typer.Option(help=f"Stop after this stage ({', '.join(STAGES)}).")
    ] = None,
    redo_from: Annotated[
        str | None, typer.Option(help="Redo this stage and every later one.")
    ] = None,
    force: Annotated[
        bool, typer.Option(help="Redo stages whose output exists.")
    ] = False,
) -> None:
    """Nadir-free faces -> OpenMVS densify/mesh/refine -> tiles -> texture -> pack."""
    _logging()
    for name, value in (("--until", until), ("--redo-from", redo_from)):
        if value is not None and value not in STAGES:
            raise typer.BadParameter(f"{name} must be one of {STAGES}")
    workspace = paths.recon_dir() / run
    cfg = DenseConfig(
        run=run,
        model=model,
        resolution_level=resolution_level,
        number_views=number_views,
        fusion_depth_diff=fusion_depth_diff,
        max_support_m=max_support_m,
        min_image_observations=min_image_observations,
        refine=refine,
        refine_resolution_level=refine_resolution_level,
        refine_decimate=refine_decimate,
        crop_margin_m=crop_margin_m,
        max_tile_faces=max_tile_faces,
        max_texture_px=max_texture_px,
        timeout_s=timeout_h * 3600.0,
        force=force,
        redo_from=redo_from,
    )
    runner = DenseRunner(
        cfg,
        workspace,
        paths.data_dir() / "out" / "mesh",
        _georef(workspace, model),
        Tools.from_env(),
    )
    report = runner.run(until=until)
    typer.echo(f"timings (s): {report.seconds}")
    typer.echo(f"stats: {json.dumps(report.stats)[:2000]}")
    typer.echo(f"report: {runner.paths.report}")


def _model_points(
    workspace: Path, model: int
) -> tuple[FloatArray, FloatArray | None, str]:
    """ENU points (and normals) of a model: the dense cloud, else sparse points."""
    to_enu = model_to_enu(_georef(workspace, model))
    dense = workspace / f"dense_m{model}" / "scene_dense.ply"
    if dense.is_file():
        vertex = read_ply(dense)["vertex"]
        xyz = np.stack([vertex["x"], vertex["y"], vertex["z"]], axis=1)
        normals = None
        if "nz" in vertex:
            raw = np.stack([vertex["nx"], vertex["ny"], vertex["nz"]], axis=1)
            normals = raw.astype(np.float64) @ to_enu.rotation.T
        return to_enu.apply(xyz.astype(np.float64)), normals, "dense"
    import pycolmap

    rec = pycolmap.Reconstruction(workspace / "sparse" / str(model))
    xyz = np.array([p.xyz for p in rec.points3D.values()], dtype=np.float64)
    return to_enu.apply(xyz), None, "sparse"


@app.command("heights")
def dense_heights(
    run: Annotated[str, typer.Option(help="SfM run name under data/recon/.")],
    model: Annotated[
        list[int], typer.Option(help="Georeferenced model index (repeatable).")
    ],
    min_inside: Annotated[
        int, typer.Option(help="Points needed inside the footprint.")
    ] = 30,
) -> None:
    """Per-footprint heights from the point cloud -> data/derived/sfm_heights.json."""
    workspace = paths.recon_dir() / run
    clouds: list[FloatArray] = []
    normals: list[FloatArray | None] = []
    for index in model:
        pts, nrm, kind = _model_points(workspace, index)
        typer.echo(f"model {index}: {len(pts)} {kind} points")
        clouds.append(pts)
        normals.append(nrm)
    points = np.concatenate(clouds)
    known = [n for n in normals if n is not None]
    all_normals = np.concatenate(known) if len(known) == len(normals) else None
    buildings = json.loads(
        (paths.data_dir() / "out" / "buildings.json").read_text("utf-8")
    )["buildings"]
    footprints = [(str(b["id"]), Polygon(b["outline"])) for b in buildings]
    params = HeightParams(min_inside=min_inside)
    heights = building_heights(points, footprints, params, all_normals)
    out = paths.derived_dir() / "sfm_heights.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({k: v.as_json() for k, v in sorted(heights.items())}, indent=2)
        + "\n",
        "utf-8",
    )
    by_id = {str(b["id"]): b for b in buildings}
    for fid, h in sorted(heights.items(), key=lambda kv: -kv[1].points):
        b = by_id[fid]
        typer.echo(
            f"{fid:>18} {str(b.get('name') or '')[:32]:32} sfm {h.height_m:5.1f} m "
            f"(ground {h.ground_m:+.1f}, {h.points} pts) | before {b['height_m']} m "
            f"[{b.get('height_source')}], levels {b.get('levels')}"
        )
    typer.echo(f"{len(heights)} heights accepted -> {out}")
