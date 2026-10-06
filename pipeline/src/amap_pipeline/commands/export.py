"""``amap export``: produce web assets under data/out/."""

import json
from typing import Annotated

import typer

from amap_pipeline import paths
from amap_pipeline.export.assets import (
    MassingParams,
    export_panos,
    greenery_json,
    ground_json,
    massing,
    write_massing,
)
from amap_pipeline.geo.osm import (
    CAMPUS_OSM_BBOX,
    LocalProjector,
    fetch_buildings_raw,
    fetch_greenery_raw,
    fetch_ground_raw,
    parse_buildings,
    parse_greenery,
    parse_ground,
)

app = typer.Typer(help="Web asset export commands.", no_args_is_help=True)


@app.command("buildings")
def export_buildings(
    radius_m: Annotated[float, typer.Option(help="Keep buildings within.")] = 450.0,
) -> None:
    """Write data/out/buildings.json (OSM massing in local metres)."""
    buildings = parse_buildings(
        fetch_buildings_raw(
            CAMPUS_OSM_BBOX, paths.data_dir() / "osm" / "buildings.json"
        ),
        LocalProjector(),
    )
    data = massing(buildings, MassingParams(radius_m=radius_m))
    out = paths.data_dir() / "out" / "buildings.json"
    write_massing(out, data)
    campus = sum(1 for b in data["buildings"] if b["campus"])
    typer.echo(f"wrote {len(data['buildings'])} buildings ({campus} campus) -> {out}")


@app.command("panos")
def export_panos_cmd(
    all_scenes: Annotated[
        bool, typer.Option("--all", help="Every Florya scene, not just graph nodes.")
    ] = False,
) -> None:
    """Convert cube faces of graph nodes (or all scenes) to WebP for the viewer."""
    out_dir = paths.data_dir() / "out"
    if all_scenes:
        scenes = (paths.sets_dir() / "florya_all.txt").read_text("utf-8").split()
    else:
        graph = json.loads((out_dir / "graph.geojson").read_text("utf-8"))
        scenes = [
            f["id"] for f in graph["features"] if f["properties"]["feature"] == "node"
        ]
    count = export_panos(scenes, paths.tiles_dir(), out_dir / "panos")
    typer.echo(f"wrote {count} WebP faces for {len(scenes)} scenes")


@app.command("greenery")
def export_greenery(
    radius_m: Annotated[float, typer.Option(help="Keep features within.")] = 450.0,
) -> None:
    """Write data/out/greenery.json (OSM parks, grass and trees)."""
    greenery = parse_greenery(
        fetch_greenery_raw(CAMPUS_OSM_BBOX, paths.data_dir() / "osm" / "greenery.json"),
        LocalProjector(),
    )
    data = greenery_json(greenery, radius_m)
    out = paths.data_dir() / "out" / "greenery.json"
    write_massing(out, data)
    typer.echo(
        f"wrote {len(data['areas'])} areas and {len(data['trees'])} trees -> {out}"
    )


@app.command("ground")
def export_ground(
    radius_m: Annotated[float, typer.Option(help="Keep features within.")] = 600.0,
) -> None:
    """Write data/out/ground.json (OSM streets, footpaths and ground areas)."""
    ground = parse_ground(
        fetch_ground_raw(CAMPUS_OSM_BBOX, paths.data_dir() / "osm" / "ground.json"),
        LocalProjector(),
    )
    data = ground_json(ground, radius_m)
    out = paths.data_dir() / "out" / "ground.json"
    write_massing(out, data)
    typer.echo(
        f"wrote {len(data['ways'])} ways and {len(data['areas'])} areas -> {out}"
    )
