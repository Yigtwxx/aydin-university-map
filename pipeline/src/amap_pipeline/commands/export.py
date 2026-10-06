"""``amap export``: produce web assets under data/out/."""

import json
import logging
from typing import Annotated, Any

import typer
from shapely.ops import unary_union

from amap_pipeline import paths
from amap_pipeline.export.assets import (
    MassingParams,
    export_panos,
    greenery_json,
    ground_json,
    massing,
    region_json,
    write_massing,
)
from amap_pipeline.geo.context import fetch_context_raw, parse_context
from amap_pipeline.geo.earth import MAX_WORKERS, EarthPaths, build_earth
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
from amap_pipeline.geo.region import (
    LAND_BBOX,
    ROADS_BBOX,
    SEA_BBOX,
    fetch_aeroway_raw,
    fetch_coastline_raw,
    fetch_land_raw,
    fetch_roads_raw,
    parse_aeroways,
    parse_land,
    parse_roads,
    parse_sea,
)

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
    buildings = parse_buildings(
        fetch_buildings_raw(WIDE_OSM_BBOX, osm_dir / "buildings_wide.json"),
        projector,
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


@app.command("region")
def export_region(
    land_tolerance_m: Annotated[
        float, typer.Option(help="Land simplification.")
    ] = 120.0,
    sea_tolerance_m: Annotated[float, typer.Option(help="Sea simplification.")] = 4.0,
    road_tolerance_m: Annotated[
        float, typer.Option(help="Road simplification.")
    ] = 16.0,
) -> None:
    """Write data/out/region.json (land, near-shore sea, trunk roads, runways)."""
    data_dir = paths.data_dir()
    projector = LocalProjector()
    land = parse_land(
        fetch_land_raw(data_dir / "natural_earth" / "ne_10m_land.geojson"),
        projector,
        LAND_BBOX,
        land_tolerance_m,
    )
    sea = parse_sea(
        fetch_coastline_raw(SEA_BBOX, data_dir / "osm" / "coastline_florya.json"),
        projector,
        SEA_BBOX,
        sea_tolerance_m,
    )
    roads = parse_roads(
        fetch_roads_raw(ROADS_BBOX, data_dir / "osm" / "roads_region.json"),
        projector,
        road_tolerance_m,
    )
    runways, aerodromes = parse_aeroways(
        fetch_aeroway_raw(ROADS_BBOX, data_dir / "osm" / "aeroway_region.json"),
        projector,
    )
    campus: list[dict[str, Any]] = []
    ground_path = data_dir / "out" / "ground.json"
    if ground_path.is_file():
        ground = json.loads(ground_path.read_text("utf-8"))
        campus = [a for a in ground.get("areas", []) if a.get("kind") == "campus"]
    data = region_json(land, sea, roads, runways, aerodromes, campus)
    out = data_dir / "out" / "region.json"
    write_massing(out, data)
    typer.echo(
        f"wrote {len(data['land'])} land, {len(data['sea_near'])} sea, "
        f"{len(data['roads'])} roads, {len(data['runways'])} runways, "
        f"{len(data['aerodromes'])} aerodromes, {len(campus)} campus "
        f"({out.stat().st_size / 1024:.0f} KB) -> {out}"
    )


@app.command("earth")
def export_earth(
    workers: Annotated[
        int,
        typer.Option(min=1, max=MAX_WORKERS, help="Concurrent tile downloads."),
    ] = MAX_WORKERS,
) -> None:
    """Write data/out/earth/ (day, night, height, water textures + earth.json)."""
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
        )
    earth_paths = EarthPaths.under(paths.data_dir())
    files = build_earth(earth_paths, workers=workers)
    total = 0
    for file in files:
        size = file.stat().st_size
        total += size
        typer.echo(f"{file.name:<16} {size / 1024:>8.0f} KB")
    typer.echo(f"{'total':<16} {total / 1024**2:>8.2f} MB -> {earth_paths.out_dir}")
