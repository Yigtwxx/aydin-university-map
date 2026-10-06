"""Give the API its own least-privilege database login.

The ``amap_api`` role is created (without login) by the first migration; this
sets a fresh random password and writes the API's connection string, using
the transaction pooler (port 6543, IPv4), to ``.env`` as
``AMAP_API_DATABASE_URL``. Neither value is ever printed.
"""

import secrets
import urllib.parse

import psycopg
from psycopg import sql

API_ROLE = "amap_api"
TRANSACTION_POOLER_PORT = 6543


def api_database_url(session_pooler_url: str, password: str) -> str:
    """Same pooler host, the API role (``amap_api.<project ref>``), port 6543."""
    parts = urllib.parse.urlsplit(session_pooler_url)
    user = parts.username or ""
    if "." not in user:
        raise ValueError("expected a Supabase pooler user like postgres.<ref>")
    project_ref = user.split(".", 1)[1]
    netloc = (
        f"{API_ROLE}.{project_ref}:{urllib.parse.quote(password, safe='')}"
        f"@{parts.hostname}:{TRANSACTION_POOLER_PORT}"
    )
    return urllib.parse.urlunsplit(
        (parts.scheme, netloc, parts.path or "/postgres", "", "")
    )


def rotate_api_password(conn: psycopg.Connection) -> str:
    password = secrets.token_urlsafe(32)
    conn.execute(
        sql.SQL("alter role {} with login password {}").format(
            sql.Identifier(API_ROLE), sql.Literal(password)
        )
    )
    return password
