"""``amap`` command line entry point."""

import typer

from amap_pipeline.commands import georef, graph, rig, sfm, tiles, tour

app = typer.Typer(help="Aydın University Map offline pipeline.", no_args_is_help=True)
app.add_typer(tour.app, name="tour")
app.add_typer(tiles.app, name="tiles")
app.add_typer(rig.app, name="rig")
app.add_typer(sfm.app, name="sfm")
app.add_typer(georef.app, name="georef")
app.add_typer(graph.app, name="graph")
