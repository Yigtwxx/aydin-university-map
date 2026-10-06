"""API behaviour with and without the optional database (fake, no network)."""

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

# conftest's FakeDatabase (pytest runs in importlib mode, so it isn't importable).
FakeDatabase = Any


def test_health_without_database_reports_off(client: TestClient) -> None:
    assert client.get("/health").json()["database"] == "off"


def test_health_with_database_runs_ping(db_client: TestClient) -> None:
    assert db_client.get("/health").json()["database"] == "ok"


def test_health_reports_unavailable_database(
    db_client: TestClient, fake_db: FakeDatabase
) -> None:
    fake_db.healthy = False
    assert db_client.get("/health").json()["database"] == "unavailable"


def test_buildings_need_a_database(client: TestClient) -> None:
    assert client.get("/buildings").status_code == 503


def test_buildings_default_to_campus_blocks(db_client: TestClient) -> None:
    body = db_client.get("/buildings").json()
    assert [b["code"] for b in body] == ["A"], body
    assert len(db_client.get("/buildings", params={"campus": False}).json()) == 2


def test_places_typo_falls_back_to_trigram_search(
    db_client: TestClient, fake_db: FakeDatabase
) -> None:
    body = db_client.get("/places", params={"q": "kutphane"}).json()
    assert [p["name_tr"] for p in body] == ["Kütüphane Giriş"], body
    assert fake_db.similar_calls == ["kutphane"], fake_db.similar_calls


def test_places_prefix_hit_skips_trigram_search(
    db_client: TestClient, fake_db: FakeDatabase
) -> None:
    db_client.get("/places", params={"q": "kampus"})
    assert fake_db.similar_calls == [], "no trigram query when prefix search found"


@pytest.mark.db
@pytest.mark.skipif(
    not os.environ.get("AMAP_API_DATABASE_URL"),
    reason="needs AMAP_API_DATABASE_URL (live Supabase)",
)
def test_live_database_answers_ping_and_buildings() -> None:
    import asyncio

    from amap_api.db import Database

    async def check() -> tuple[bool, int]:
        db = Database(os.environ["AMAP_API_DATABASE_URL"])
        await db.open()
        try:
            return await db.ping(), len(await db.buildings(campus_only=True))
        finally:
            await db.close()

    ok, campus = asyncio.run(check())
    assert ok, "live ping failed"
    assert campus >= 1, "expected campus buildings in amap.buildings"
