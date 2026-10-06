import hashlib
import json
import threading
from collections.abc import Iterator
from http.client import HTTPConnection, HTTPResponse
from pathlib import Path

import pytest

from amap_pipeline.acquire.sink import DEFAULT_ORIGIN, SinkConfig, make_server
from amap_pipeline.acquire.store import TileStore

TOKEN = "test-token"


@pytest.fixture
def sink_port(tile_store: TileStore, sets_dir: Path) -> Iterator[int]:
    cfg = SinkConfig(
        store=tile_store, sets_dir=sets_dir, token=TOKEN, log=lambda _: None
    )
    server = make_server(cfg, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def _request(
    port: int,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[HTTPResponse, bytes]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    payload = response.read()
    conn.close()
    return response, payload


def test_sink_preflight_allows_tour_origin_and_private_network(sink_port: int) -> None:
    response, _ = _request(
        sink_port,
        "OPTIONS",
        "/tile/scene_1/f",
        headers={
            "Origin": DEFAULT_ORIGIN,
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert response.status == 204, f"Got {response.status}"
    assert response.getheader("Access-Control-Allow-Origin") == DEFAULT_ORIGIN
    assert response.getheader("Access-Control-Allow-Private-Network") == "true"
    assert "X-SHA256" in (response.getheader("Access-Control-Allow-Headers") or "")


@pytest.mark.parametrize("token", [None, "wrong"])
def test_sink_queue_without_valid_token_returns_401(
    sink_port: int, token: str | None
) -> None:
    headers = {"X-Sink-Token": token} if token else {}
    response, _ = _request(sink_port, "GET", "/queue?set=mini", headers=headers)
    assert response.status == 401, f"Got {response.status}"


def test_sink_queue_lists_missing_faces(sink_port: int) -> None:
    response, payload = _request(
        sink_port, "GET", "/queue?set=mini", headers={"X-Sink-Token": TOKEN}
    )
    data = json.loads(payload)
    assert response.status == 200, f"Got {response.status}: {data}"
    assert data["scenes"] == ["scene_1", "scene_2"], f"Got {data['scenes']}"
    assert len(data["missing"]) == 12, f"Got {len(data['missing'])}"


def test_sink_queue_unknown_set_returns_400(sink_port: int) -> None:
    response, _ = _request(
        sink_port, "GET", "/queue?set=../secrets", headers={"X-Sink-Token": TOKEN}
    )
    assert response.status == 400, f"Got {response.status}"


def test_sink_post_tile_saves_and_dequeues(
    sink_port: int, tile_store: TileStore, jpeg_bytes: bytes
) -> None:
    response, payload = _request(
        sink_port,
        "POST",
        "/tile/scene_1/f",
        body=jpeg_bytes,
        headers={
            "X-Sink-Token": TOKEN,
            "X-SHA256": hashlib.sha256(jpeg_bytes).hexdigest(),
            "Content-Type": "image/jpeg",
        },
    )
    assert response.status == 200, f"Got {response.status}: {payload!r}"
    assert tile_store.has("scene_1", "f"), "Tile was not written"


def test_sink_post_tile_bad_hash_returns_400(sink_port: int, jpeg_bytes: bytes) -> None:
    response, _ = _request(
        sink_port,
        "POST",
        "/tile/scene_1/f",
        body=jpeg_bytes,
        headers={"X-Sink-Token": TOKEN, "X-SHA256": "0" * 64},
    )
    assert response.status == 400, f"Got {response.status}"


def test_make_server_non_loopback_host_raises_value_error(
    tile_store: TileStore, sets_dir: Path
) -> None:
    cfg = SinkConfig(store=tile_store, sets_dir=sets_dir, token=TOKEN)
    with pytest.raises(ValueError, match="loopback"):
        make_server(cfg, "0.0.0.0", 0)
