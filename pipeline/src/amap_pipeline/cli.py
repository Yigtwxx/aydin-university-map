"""``amap`` command line entry point."""

import typer

from amap_pipeline.commands import tiles, tour

app = typer.Typer(help="Aydın University Map offline pipeline.", no_args_is_help=True)
app.add_typer(tour.app, name="tour")
app.add_typer(tiles.app, name="tiles")
