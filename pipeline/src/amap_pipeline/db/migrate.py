"""Apply ``supabase/migrations/*.sql`` in order, each once, in a transaction."""

from dataclasses import dataclass
from pathlib import Path
from typing import LiteralString, cast

import psycopg

LEDGER = """
create schema if not exists amap;
create table if not exists amap.schema_migrations (
  version text primary key,
  applied_at timestamptz not null default now()
);
"""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    applied: list[str]
    skipped: list[str]


def migration_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.sql"))


def migrate(conn: psycopg.Connection, directory: Path) -> MigrationResult:
    with conn.transaction():
        conn.execute(LEDGER)
    done = {
        row[0] for row in conn.execute("select version from amap.schema_migrations")
    }
    applied: list[str] = []
    skipped: list[str] = []
    for path in migration_files(directory):
        version = path.stem
        if version in done:
            skipped.append(version)
            continue
        with conn.transaction():
            # Migration files are trusted repo content, not user input.
            conn.execute(cast(LiteralString, path.read_text("utf-8")))
            conn.execute(
                "insert into amap.schema_migrations (version) values (%s)", (version,)
            )
        applied.append(version)
    return MigrationResult(applied, skipped)
