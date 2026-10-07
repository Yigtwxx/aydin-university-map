"""Points of interest through the API: listing, search and routing to them."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amap_api.graph_store import GraphStore, load_pois
from amap_api.main import create_app
from amap_api.settings import Settings

POIS = {
    "schema_version": 1,
    "generated_at": "2026-10-07T00:00:00Z",
    "pois": [
        {
            "id": "burger-king",
            "name": {"tr": "Burger King", "en": "Burger King"},
            "category": "food",
            "brand": "Burger King",
            "aliases": ["bk"],
            "node_id": "c",
            "pin_enu": [41.0, 3.0],
        },
        {
            "id": "atm",
            "name": {"tr": "ATM", "en": "Cash machine"},
            "category": "atm",
            "node_id": "b",
            "own_panorama": False,
            "pin_enu": [20.0, 1.0],
        },
    ],
}


@pytest.fixture
def poi_client(store: GraphStore, tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "pois.json"
    path.write_text(json.dumps(POIS), encoding="utf-8")
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        graph_source="unused",
        pois_source=str(path),
        cors_origins="http://localhost:3000",
    )
    with TestClient(create_app(settings=settings, store=store)) as client:
        yield client


def test_pois_source_defaults_next_to_the_graph() -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        graph_source="https://assets.example/graph.geojson",
    )
    assert settings.pois_location == "https://assets.example/pois.json"


def test_missing_pois_file_means_none(tmp_path: Path) -> None:
    assert load_pois(str(tmp_path / "absent.json")) == []


def test_directory_lists_pois_with_category_and_pin(poi_client: TestClient) -> None:
    listed = {p["id"]: p for p in poi_client.get("/places?limit=50").json()}
    assert listed["c"]["category"] == "food"
    assert listed["c"]["pin_enu"] == [41.0, 3.0]
    assert listed["poi:atm"]["category"] == "atm"


def test_search_finds_poi_by_alias(poi_client: TestClient) -> None:
    found = poi_client.get("/places", params={"q": "bk"}).json()
    assert [p["id"] for p in found] == ["c"]
    assert found[0]["brand"] == "Burger King"


def test_route_to_a_poi_place_uses_its_panorama(poi_client: TestClient) -> None:
    response = poi_client.post("/route", json={"source": "a", "target": "poi:atm"})
    assert response.status_code == 200, response.text
    assert response.json()["node_ids"][-1] == "b"


def test_place_lookup_by_id(poi_client: TestClient) -> None:
    response = poi_client.get("/places/poi:atm")
    assert response.status_code == 200, response.text
    assert response.json()["category"] == "atm"
    assert poi_client.get("/places/c").json()["brand"] == "Burger King"
    assert poi_client.get("/places/nope").status_code == 404


def test_directory_accepts_a_large_limit(poi_client: TestClient) -> None:
    assert poi_client.get("/places?limit=500").status_code == 200
