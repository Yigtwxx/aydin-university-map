"""``amap graph``: export the metric walking graph as GeoJSON."""

import json
from typing import Annotated, Any

import typer

from amap_pipeline import paths
from amap_pipeline.geo.align import footprint_union
from amap_pipeline.geo.osm import (
    CAMPUS_OSM_BBOX,
    LocalProjector,
    fetch_buildings_raw,
    parse_buildings,
)
from amap_pipeline.graph.build import GraphParams, build_graph, summarise

app = typer.Typer(help="Walking graph commands.", no_args_is_help=True)


@app.command("export")
def graph_export(
    runs: Annotated[
        list[str], typer.Option("--run", help="Georeferenced SfM run (repeatable).")
    ],
    max_link_m: Annotated[float, typer.Option(help="Longer links are teleports.")] = 60,
    infer_radius_m: Annotated[float, typer.Option(help="Line-of-sight radius.")] = 12,
) -> None:
    """Merge georeferenced runs and write data/out/graph.geojson + report."""
    posed: dict[str, dict[str, Any]] = {}
    for run in runs:
        georef = json.loads(
            (paths.recon_dir() / run / "georef.json").read_text("utf-8")
        )
        for scene, record in georef["scenes"].items():
            posed.setdefault(scene, record)
    scenes = {
        s["name"]: s
        for s in json.loads((paths.derived_dir() / "scenes.json").read_text("utf-8"))
    }
    buildings = parse_buildings(
        fetch_buildings_raw(
            CAMPUS_OSM_BBOX, paths.data_dir() / "osm" / "buildings.json"
        ),
        LocalProjector(),
    )
    graph, report = build_graph(
        posed,
        scenes,
        footprint_union([b.outline for b in buildings]),
        run_id="+".join(runs),
        params=GraphParams(max_link_m=max_link_m, infer_radius_m=infer_radius_m),
    )
    out_dir = paths.data_dir() / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "graph.geojson").write_text(
        json.dumps(graph.to_geojson(), ensure_ascii=False) + "\n", "utf-8"
    )
    summary = summarise(graph, report)
    (out_dir / "graph_report.json").write_text(
        json.dumps({"summary": summary, "dropped": report.dropped}, indent=2) + "\n",
        "utf-8",
    )
    typer.echo(json.dumps(summary, ensure_ascii=False))
    typer.echo(f"wrote {out_dir / 'graph.geojson'}")
