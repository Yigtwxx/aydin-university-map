"""``amap tiles``: receive cube-face tiles from the browser and verify them."""

import secrets
from typing import Annotated

import typer

from amap_pipeline import paths
from amap_pipeline.acquire.sink import (
    DEFAULT_ORIGIN,
    SinkConfig,
    make_server,
    read_scene_set,
)
from amap_pipeline.acquire.store import TileError, TileStore, verify

app = typer.Typer(help="Tile export commands.", no_args_is_help=True)


@app.command("serve")
def tiles_serve(
    port: Annotated[int, typer.Option(help="Loopback port.")] = 8765,
    host: Annotated[str, typer.Option(help="Loopback host.")] = "127.0.0.1",
    token: Annotated[
        str | None, typer.Option(help="Session token (random if omitted).")
    ] = None,
    origin: Annotated[str, typer.Option(help="Allowed CORS origin.")] = DEFAULT_ORIGIN,
) -> None:
    """Run the loopback sink that writes data/tiles/<scene>/<face>.jpg."""
    session_token = token or secrets.token_urlsafe(24)
    cfg = SinkConfig(
        store=TileStore(paths.tiles_dir()),
        sets_dir=paths.sets_dir(),
        token=session_token,
        allowed_origin=origin,
    )
    server = make_server(cfg, host, port)
    typer.echo(f"sink listening on http://{host}:{port}  origin={origin}")
    if token is None:
        typer.echo(f"session token: {session_token}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("stopping sink")
    finally:
        server.server_close()


@app.command("verify")
def tiles_verify(
    set_name: Annotated[str, typer.Option("--set", help="Scene set name.")],
) -> None:
    """Check that every scene of a set has 6 complete, correctly sized faces."""
    try:
        scenes = read_scene_set(paths.sets_dir(), set_name)
    except TileError as exc:
        raise typer.BadParameter(str(exc)) from exc
    report = verify(TileStore(paths.tiles_dir()), scenes)
    typer.echo(
        f"{set_name}: {len(report.complete)}/{len(scenes)} scenes complete, "
        f"{len(report.missing)} faces missing, {len(report.corrupt)} corrupt"
    )
    for scene, face, reason in report.corrupt:
        typer.echo(f"  corrupt {scene}/{face}: {reason}")
    if not report.ok:
        raise typer.Exit(code=1)
