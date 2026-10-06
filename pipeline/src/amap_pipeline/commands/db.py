"""``amap db``: migrations, the API's login and loading pipeline outputs."""

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from amap_pipeline import paths

if TYPE_CHECKING:
    import psycopg

# psycopg and the env loader come with the `db` extra; import them in the
# commands so the rest of the CLI works without it.

app = typer.Typer(help="Supabase database commands.", no_args_is_help=True)

MIGRATIONS_DIR = Path(__file__).parents[4] / "supabase" / "migrations"
# Session pooler (IPv4); the direct host is IPv6-only.
ADMIN_URL_ENV = "DATABASE_POOLER_URL"
API_URL_ENV = "AMAP_API_DATABASE_URL"


def _connect() -> "psycopg.Connection":
    import psycopg

    from amap_pipeline.env import require_env

    return psycopg.connect(require_env(ADMIN_URL_ENV), autocommit=True)


@app.command("migrate")
def db_migrate() -> None:
    """Apply new files from supabase/migrations/ (each once)."""
    from amap_pipeline.db.migrate import migrate

    with _connect() as conn:
        result = migrate(conn, MIGRATIONS_DIR)
    typer.echo(
        f"applied {result.applied or 'nothing'}; already applied {result.skipped}"
    )


@app.command("api-role")
def db_api_role() -> None:
    """Rotate the amap_api password and write AMAP_API_DATABASE_URL to .env."""
    from amap_pipeline.db.api_role import api_database_url, rotate_api_password
    from amap_pipeline.env import require_env, set_env_value

    admin_url = require_env(ADMIN_URL_ENV)
    with _connect() as conn:
        password = rotate_api_password(conn)
    set_env_value(API_URL_ENV, api_database_url(admin_url, password))
    typer.echo(f"{API_URL_ENV} written to .env (transaction pooler, role amap_api)")


@app.command("load")
def db_load() -> None:
    """Replace buildings, nodes, edges and places with data/out."""
    from amap_pipeline.db.load import load_outputs

    with _connect() as conn:
        counts = load_outputs(conn, paths.data_dir() / "out")
    typer.echo(
        f"loaded {counts.buildings} buildings, {counts.nodes} nodes, "
        f"{counts.edges} edges, {counts.places} places"
    )


@app.command("status")
def db_status() -> None:
    """Applied migrations and row counts."""
    with _connect() as conn:
        versions = [
            r[0]
            for r in conn.execute(
                "select version from amap.schema_migrations order by version"
            )
        ]
        typer.echo(f"migrations: {versions}")
        for table in (
            "buildings",
            "nodes",
            "edges",
            "places",
            "chunks",
            "answer_cache",
        ):
            row = conn.execute(f"select count(*) from amap.{table}").fetchone()
            typer.echo(f"  {table}: {row[0] if row else 0}")
