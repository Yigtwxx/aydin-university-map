from fastapi.testclient import TestClient


def test_health_reports_loaded_graph(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["graph_loaded"] is True, body
    assert (body["nodes"], body["edges"]) == (5, 4), body


def test_places_search_folds_turkish_characters(client: TestClient) -> None:
    body = client.get("/places", params={"q": "kutuphane"}).json()
    assert [p["name_tr"] for p in body] == ["Kütüphane Giriş"], body


def test_places_search_groups_panoramas_by_label(client: TestClient) -> None:
    body = client.get("/places", params={"q": "KAMPÜS"}).json()
    assert body[0]["node_ids"] == ["a", "b"], body


def test_route_returns_steps_and_coordinates(client: TestClient) -> None:
    response = client.post("/route", json={"source": "a", "target": "c"})
    body = response.json()
    assert response.status_code == 200, body
    assert body["node_ids"] == ["a", "b", "c"], body
    assert len(body["coordinates"]) == 3, body
    assert body["steps"][-1]["text_en"] == "You have arrived: A Block Entrance", body


def test_route_unknown_node_returns_404(client: TestClient) -> None:
    response = client.post("/route", json={"source": "a", "target": "nope"})
    assert response.status_code == 404, response.text


def test_route_unreachable_returns_422(client: TestClient) -> None:
    response = client.post("/route", json={"source": "a", "target": "e"})
    assert response.status_code == 422, response.text


def test_nearest_node_snaps_map_click(client: TestClient) -> None:
    body = client.get("/nodes/nearest", params={"lat": 40.99168, "lng": 28.7971}).json()
    assert body["node_id"] == "b", body


def test_cors_allows_configured_web_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_places_search_short_word_matches_word_start_only(client: TestClient) -> None:
    body = client.get("/places", params={"q": "a blok"}).json()
    assert [p["name_tr"] for p in body] == ["A Blok Girişi"], body
