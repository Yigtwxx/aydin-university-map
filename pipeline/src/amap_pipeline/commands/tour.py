"""``amap tour``: classify scenes and select connected scene sets."""

import json
from pathlib import Path
from typing import Annotated

import typer

from amap_pipeline import paths
from amap_pipeline.tour import SceneKind, bfs_select, load_dump, load_overrides
from amap_pipeline.tour.export import (
    ClassifiedTour,
    classify_tour,
    summary,
    write_scenes,
)

app = typer.Typer(help="Tour metadata commands.", no_args_is_help=True)

RawOption = Annotated[Path | None, typer.Option(help="krpano dump JSON.")]
OverridesOption = Annotated[
    Path | None, typer.Option(help="TOML file with [overrides] scene = kind.")
]


def _load(raw: Path | None, overrides: Path | None) -> ClassifiedTour:
    raw_path = raw or paths.raw_dump()
    overrides_path = overrides or paths.derived_dir() / "scene_overrides.toml"
    return classify_tour(load_dump(raw_path), load_overrides(overrides_path))


@app.command("build")
def tour_build(
    raw: RawOption = None,
    overrides: OverridesOption = None,
    out: Annotated[Path | None, typer.Option(help="Output scenes JSON.")] = None,
) -> None:
    """Classify Florya scenes and write data/derived/scenes.json."""
    tour = _load(raw, overrides)
    out_path = out or paths.derived_dir() / "scenes.json"
    write_scenes(tour, out_path)
    typer.echo(json.dumps(summary(tour), ensure_ascii=False))
    typer.echo(f"wrote {out_path}")


@app.command("select")
def tour_select(
    hub: Annotated[str, typer.Option(help="Start scene name.")],
    n: Annotated[int, typer.Option(help="Number of scenes to select.")],
    name: Annotated[str, typer.Option(help="Set name, e.g. spike35.")],
    raw: RawOption = None,
    overrides: OverridesOption = None,
    indoor: Annotated[bool, typer.Option(help="Also walk indoor scenes.")] = False,
) -> None:
    """BFS-select a connected scene set and write data/derived/sets/<name>.txt."""
    tour = _load(raw, overrides)
    allowed = (
        None if indoor else tour.names_of_kind(SceneKind.OUTDOOR, SceneKind.ENTRANCE)
    )
    selected = bfs_select(tour.adjacency, hub, n, allowed)
    out_path = paths.derived_dir() / "sets" / f"{name}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(selected) + "\n", encoding="utf-8")
    kinds = {k.value: 0 for k in SceneKind}
    for scene_name in selected:
        kinds[tour.kinds[scene_name].value] += 1
    typer.echo(f"selected {len(selected)} scenes {kinds} -> {out_path}")


@app.command("select-all")
def tour_select_all(
    hub: Annotated[str, typer.Option(help="Outdoor hub to order the set from.")],
    name: Annotated[str, typer.Option(help="Set name, e.g. florya_all.")],
    raw: RawOption = None,
    overrides: OverridesOption = None,
) -> None:
    """Every Florya scene: outdoor/entrance first (BFS from hub), then the rest."""
    tour = _load(raw, overrides)
    outdoor = tour.names_of_kind(SceneKind.OUTDOOR, SceneKind.ENTRANCE)
    ordered = bfs_select(tour.adjacency, hub, len(outdoor), outdoor)
    seen = set(ordered)
    ordered += [s.name for s in tour.scenes if s.name in outdoor and s.name not in seen]
    seen = set(ordered)
    ordered += [s.name for s in tour.scenes if s.name not in seen]
    out_path = paths.sets_dir() / f"{name}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(ordered) + "\n", encoding="utf-8")
    typer.echo(
        f"selected {len(ordered)} scenes ({len(outdoor)} outdoor/entrance first)"
    )
