"""``amap publish``: push web assets (data/out) to Cloudflare Pages (ADR-0004)."""

import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from amap_pipeline import paths

app = typer.Typer(help="Publishing commands.", no_args_is_help=True)

DEFAULT_PROJECT = "aydin-campus-assets"
# Panorama faces and JSON keep stable names, so caches expire instead of
# being immutable; the browser revalidates JSON hourly.
HEADERS = """/*
  Access-Control-Allow-Origin: *
  Cache-Control: public, max-age=3600
  X-Content-Type-Options: nosniff

/panos/*
  ! Cache-Control
  Cache-Control: public, max-age=604800, stale-while-revalidate=86400
"""


def write_headers(out_dir: Path) -> Path:
    path = out_dir / "_headers"
    path.write_text(HEADERS, encoding="utf-8")
    return path


@app.command("assets")
def publish_assets(
    project: Annotated[str, typer.Option(help="Cloudflare Pages project.")] = (
        DEFAULT_PROJECT
    ),
    create: Annotated[
        bool, typer.Option(help="Create the Pages project first if it is missing.")
    ] = False,
) -> None:
    """Deploy data/out with `wrangler pages deploy` (wrangler login or API token)."""
    out_dir = paths.data_dir() / "out"
    if not (out_dir / "graph.geojson").is_file():
        raise typer.BadParameter("data/out has no graph.geojson; export first")
    write_headers(out_dir)
    npx = shutil.which("npx")
    if npx is None:
        raise typer.BadParameter("npx (Node.js) is required for wrangler")
    wrangler = [npx, "--yes", "wrangler@4"]
    if create:
        # --force keeps a plain Pages project (wrangler 4 otherwise delegates
        # new projects to Workers and fails at a monorepo root).
        subprocess.run(
            [*wrangler, "pages", "project", "create", project,
             "--production-branch", "main", "--force"],
            check=False,
        )  # fmt: skip
    subprocess.run(
        [*wrangler, "pages", "deploy", str(out_dir),
         "--project-name", project, "--branch", "main", "--commit-dirty=true"],
        check=True,
    )  # fmt: skip
    typer.echo(f"published {out_dir} to https://{project}.pages.dev")
