"""``amap export``: produce web assets under data/out/."""

import json
from pathlib import Path
from typing import Annotated

import typer
from shapely.ops import unary_union

from amap_pipeline import paths
from amap_pipeline.export.assets import (
    MassingParams,
    export_panos,
    greenery_json,
    ground_json,
    massing,
    write_massing,
)
from amap_pipeline.export.furniture import build_furniture, read_furniture
from amap_pipeline.export.pois import build_pois, read_poi_config
from amap_pipeline.geo.context import fetch_context_raw, parse_context
from amap_pipeline.geo.osm import (
    WIDE_OSM_BBOX,
    LocalProjector,
    fetch_buildings_raw,
    fetch_greenery_raw,
    fetch_ground_raw,
    parse_buildings,
    parse_greenery,
    parse_ground,
)
from amap_pipeline.geo.overrides import apply_building_overrides

app = typer.Typer(help="Web asset export commands.", no_args_is_help=True)

# Streets whose blocks usually have shops at street level.
SHOP_STREETS = frozenset(
    {"trunk", "primary", "secondary", "tertiary", "primary_link", "secondary_link"}
)


@app.command("buildings")
def export_buildings(
    radius_m: Annotated[float, typer.Option(help="Keep buildings within.")] = 1200.0,
) -> None:
    """Write data/out/buildings.json (styled OSM massing in local metres)."""
    projector = LocalProjector()
    osm_dir = paths.data_dir() / "osm"
    buildings = apply_building_overrides(
        parse_buildings(
            fetch_buildings_raw(WIDE_OSM_BBOX, osm_dir / "buildings_wide.json"),
            projector,
        )
    )
    context = parse_context(
        fetch_context_raw(WIDE_OSM_BBOX, osm_dir / "context_wide.json"), projector
    )
    ground = parse_ground(
        fetch_ground_raw(WIDE_OSM_BBOX, osm_dir / "ground_wide.json"), projector
    )
    streets = unary_union([w.line for w in ground.ways if w.kind in SHOP_STREETS])
    data = massing(buildings, MassingParams(radius_m=radius_m), context, streets)
    sfm_heights = paths.derived_dir() / "sfm_heights.json"
    if sfm_heights.is_file():
        # Measured heights from the dense point cloud (``amap dense heights``).
        from amap_pipeline.geo.sfm_heights import apply_sfm_heights

        heights = json.loads(sfm_heights.read_text("utf-8"))
        applied = apply_sfm_heights(data["buildings"], heights)
        typer.echo(f"applied {applied} SfM heights from {sfm_heights}")
    out = paths.data_dir() / "out" / "buildings.json"
    write_massing(out, data)
    styles: dict[str, int] = {}
    for b in data["buildings"]:
        styles[b["style"]] = styles.get(b["style"], 0) + 1
    summary = ", ".join(f"{k} {v}" for k, v in sorted(styles.items()))
    typer.echo(f"wrote {len(data['buildings'])} buildings ({summary}) -> {out}")


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
    radius_m: Annotated[float, typer.Option(help="Keep features within.")] = 1200.0,
) -> None:
    """Write data/out/greenery.json (OSM parks, grass and trees)."""
    greenery = parse_greenery(
        fetch_greenery_raw(
            WIDE_OSM_BBOX, paths.data_dir() / "osm" / "greenery_wide.json"
        ),
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
    radius_m: Annotated[float, typer.Option(help="Keep features within.")] = 1250.0,
) -> None:
    """Write data/out/ground.json (OSM streets, footpaths and ground areas)."""
    ground = parse_ground(
        fetch_ground_raw(WIDE_OSM_BBOX, paths.data_dir() / "osm" / "ground_wide.json"),
        LocalProjector(),
    )
    data = ground_json(ground, radius_m)
    out = paths.data_dir() / "out" / "ground.json"
    write_massing(out, data)
    typer.echo(
        f"wrote {len(data['ways'])} ways and {len(data['areas'])} areas -> {out}"
    )


@app.command("pois")
def export_pois(
    survey: Annotated[
        Path | None, typer.Option(help="Solve output with storefront tie points.")
    ] = None,
) -> None:
    """Write data/out/pois.json from configs/pois.toml and the survey's tie points."""
    out_dir = paths.data_dir() / "out"
    graph = json.loads((out_dir / "graph.geojson").read_text("utf-8"))
    nodes = {
        f["properties"]["id"]: f["properties"]
        for f in graph["features"]
        if f["properties"]["feature"] == "node"
    }
    survey_path = survey or paths.derived_dir() / "survey.json"
    landmarks = (
        json.loads(survey_path.read_text("utf-8")).get("landmarks", {})
        if survey_path.is_file()
        else {}
    )
    collection, warnings = build_pois(read_poi_config(), landmarks, nodes)
    for warning in warnings:
        typer.echo(f"warning: {warning}")
    (out_dir / "pois.json").write_text(
        collection.model_dump_json(indent=1) + "\n", "utf-8"
    )
    pinned = sum(1 for p in collection.pois if p.pin_enu is not None)
    typer.echo(
        f"{len(collection.pois)} POIs, {pinned} pinned -> {out_dir / 'pois.json'}"
    )


@app.command("furniture")
def export_furniture() -> None:
    """Write data/out/furniture.json from configs/furniture.toml."""
    collection = build_furniture(read_furniture())
    out = paths.data_dir() / "out" / "furniture.json"
    out.write_text(collection.model_dump_json(indent=1) + "\n", "utf-8")
    typer.echo(
        f"{len(collection.terraces)} terraces, "
        f"{len(collection.stairs)} stairs, {len(collection.ramps)} ramps, "
        f"{len(collection.railings)} railings, {len(collection.items)} items, "
        f"{len(collection.seating)} seating groups -> {out}"
    )
