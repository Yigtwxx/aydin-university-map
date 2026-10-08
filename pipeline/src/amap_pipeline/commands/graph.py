"""``amap graph``: export the metric walking graph as GeoJSON."""

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from amap_contracts.graph import Graph, Node, NodeKind
from amap_pipeline import paths
from amap_pipeline.export.furniture import build_furniture, read_furniture
from amap_pipeline.geo.align import footprint_union
from amap_pipeline.geo.osm import (
    WIDE_OSM_BBOX,
    LocalProjector,
    fetch_buildings_raw,
    parse_buildings,
)
from amap_pipeline.geo.overrides import (
    apply_building_overrides,
    apply_pose_overrides,
    apply_scene_fixes,
    apply_survey_poses,
    load_pose_overrides,
    load_scene_blocks,
    load_scene_fixes,
    load_survey_poses,
)
from amap_pipeline.graph.build import (
    GraphParams,
    blocked_edges,
    build_graph,
    components,
    step_free_conflicts,
    summarise,
)
from amap_pipeline.graph.stairs import mark_outdoor_stairs

app = typer.Typer(help="Walking graph commands.", no_args_is_help=True)

# A model whose fit is worse than this is not trusted for node positions.
MAX_ICP_RMS_M = 2.5
MAX_INSIDE_SHARE = 0.15


def georef_files(workspace: Path) -> list[Path]:
    """Per-model georeference files (``georef_m<N>.json``; legacy ``georef.json``)."""
    files = sorted(workspace.glob("georef_m*.json"))
    legacy = workspace / "georef.json"
    return files or ([legacy] if legacy.is_file() else [])


def trusted(georef: dict[str, Any]) -> bool:
    quality = georef["quality"]
    inside = len(quality["cameras_inside_buildings"]) / max(len(georef["scenes"]), 1)
    return quality["icp_rms_m"] <= MAX_ICP_RMS_M and inside <= MAX_INSIDE_SHARE


def merge_poses(georefs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Scene -> pose from the best-fitting trusted model that contains it."""
    best: dict[str, tuple[float, dict[str, Any]]] = {}
    for georef in georefs:
        if not trusted(georef):
            continue
        rms = float(georef["quality"]["icp_rms_m"])
        for scene, record in georef["scenes"].items():
            if scene not in best or rms < best[scene][0]:
                best[scene] = (rms, record)
    return {scene: record for scene, (_, record) in best.items()}


def is_door(node: Node) -> bool:
    """An entrance whose position is measured, not borrowed."""
    return node.kind is NodeKind.ENTRANCE and not node.approximate


def is_site(graph: Graph, component: list[str]) -> bool:
    """A separate site: an island with a measured entrance of its own.

    The girls' dormitory stands ~600 m from the campus; the tour reaches it
    only through teleport links, so it is an island, yet a real place with a
    measured door that people walk to along the street.
    """
    members = set(component)
    return any(n.id in members and is_door(n) for n in graph.nodes)


def main_network(graph: Graph) -> tuple[Graph, list[list[str]], list[list[str]]]:
    """The main walking network plus separate sites; drop the other islands.

    A stray island (no measured door) could never be reached and is dropped;
    returns the kept graph, the dropped islands and the kept sites.
    """
    comps = components(graph)
    if len(comps) <= 1:
        return graph, [], []
    sites = [c for c in comps[1:] if is_site(graph, c)]
    islands = [c for c in comps[1:] if not is_site(graph, c)]
    keep = set(comps[0]).union(*sites)
    kept = graph.model_copy(
        update={
            "nodes": [n for n in graph.nodes if n.id in keep],
            "edges": [e for e in graph.edges if e.source in keep and e.target in keep],
        }
    )
    return kept, islands, sites


@app.command("export")
def graph_export(
    runs: Annotated[
        list[str], typer.Option("--run", help="Georeferenced SfM run (repeatable).")
    ],
    max_link_m: Annotated[float, typer.Option(help="Longer links are teleports.")] = 60,
    infer_radius_m: Annotated[float, typer.Option(help="Line-of-sight radius.")] = 35,
    keep_islands: Annotated[
        bool,
        typer.Option(
            help="Keep every island; by default only separate sites with a "
            "measured entrance (the dormitory) stay beside the main network."
        ),
    ] = False,
    indoor: Annotated[
        bool, typer.Option(help="Add indoor panoramas through the tour's links.")
    ] = True,
    survey: Annotated[
        bool, typer.Option(help="Apply data/derived/survey.json poses if present.")
    ] = True,
) -> None:
    """Merge georeferenced runs and write data/out/graph.geojson + report."""
    georefs: list[dict[str, Any]] = []
    for run in runs:
        for path in georef_files(paths.recon_dir() / run):
            georef = json.loads(path.read_text("utf-8"))
            status = "ok" if trusted(georef) else "skipped (poor fit)"
            typer.echo(
                f"{path.relative_to(paths.recon_dir())}: {len(georef['scenes'])} "
                f"scenes, ICP {georef['quality']['icp_rms_m']} m, {status}"
            )
            georefs.append(georef)
    projector = LocalProjector()
    posed = merge_poses(georefs)
    if survey:
        surveyed = load_survey_poses(paths.derived_dir() / "survey.json")
        if surveyed:
            typer.echo(f"survey: {len(surveyed)} poses")
        posed = apply_survey_poses(posed, surveyed, projector)
    posed = apply_pose_overrides(posed, load_pose_overrides(), projector)
    scenes = apply_scene_fixes(
        {
            s["name"]: s
            for s in json.loads(
                (paths.derived_dir() / "scenes.json").read_text("utf-8")
            )
        },
        load_scene_fixes(),
        blocks=load_scene_blocks(),
    )
    # The same footprints the map draws (amap export buildings).
    buildings = apply_building_overrides(
        parse_buildings(
            fetch_buildings_raw(
                WIDE_OSM_BBOX, paths.data_dir() / "osm" / "buildings_wide.json"
            ),
            projector,
        )
    )
    footprints = footprint_union([b.outline for b in buildings])
    graph, report = build_graph(
        posed,
        scenes,
        footprints,
        run_id="+".join(runs),
        params=GraphParams(
            max_link_m=max_link_m, infer_radius_m=infer_radius_m, indoor=indoor
        ),
    )
    flights = build_furniture(read_furniture()).stairs
    graph, climbing = mark_outdoor_stairs(graph, flights)
    if climbing:
        typer.echo(f"outdoor stairs: {len(climbing)} edges over {len(flights)} flights")
    islands: list[list[str]] = []
    sites: list[list[str]] = []
    if not keep_islands:
        graph, islands, sites = main_network(graph)
    for site in sites:
        doors = [n.label.en for n in graph.nodes if n.id in site and is_door(n)]
        typer.echo(f"separate site: {len(site)} nodes, door {', '.join(doors)}")
    blocked = blocked_edges(graph, footprints)
    if blocked:
        raise typer.BadParameter(f"edges cut through buildings: {blocked}")
    conflicts = step_free_conflicts(graph)
    if conflicts:
        raise typer.BadParameter(f"step-free stretches change floor: {conflicts}")
    out_dir = paths.data_dir() / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "graph.geojson").write_text(
        json.dumps(graph.to_geojson(projector.to_wgs84), ensure_ascii=False) + "\n",
        "utf-8",
    )
    summary = summarise(graph, report)
    (out_dir / "graph_report.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "dropped": report.dropped,
                "snapped": report.snapped,
                "detoured": report.detoured,
                "islands": islands,
                "sites": sites,
                "bridges": report.bridged,
                "passages": [e.id for e in graph.edges if e.passage],
                "menu_jumps": report.indoor.menu_jumps,
                "door_walks": report.indoor.door_walks,
                "indoor_unreachable": report.indoor.unreachable,
            },
            indent=2,
        )
        + "\n",
        "utf-8",
    )
    typer.echo(json.dumps(summary, ensure_ascii=False))
    typer.echo(f"wrote {out_dir / 'graph.geojson'}")
