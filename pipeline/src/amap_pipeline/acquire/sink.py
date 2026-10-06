"""Loopback HTTP sink that receives cube-face tiles from an authorised browser tab.

The tour page (``allowed_origin``) fetches its own tiles and POSTs them here.
Security model: binds to loopback only, every non-preflight request must carry
the per-session ``X-Sink-Token``, CORS is restricted to the tour origin and
Private Network Access preflights are answered explicitly.
"""

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from amap_pipeline.acquire.store import MAX_TILE_BYTES, TileError, TileStore

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
DEFAULT_ORIGIN = "https://360.aydin.edu.tr"
_SET_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
_TILE_PATH_RE = re.compile(r"^/tile/(?P<scene>[^/]+)/(?P<face>[^/]+)$")


def read_scene_set(sets_dir: Path, name: str) -> list[str]:
    if not _SET_RE.fullmatch(name):
        raise TileError(f"invalid set name {name!r}")
    path = sets_dir / f"{name}.txt"
    if not path.is_file():
        raise TileError(f"unknown set {name!r}")
    return [
        line.strip() for line in path.read_text("utf-8").splitlines() if line.strip()
    ]


@dataclass(frozen=True, slots=True)
class SinkConfig:
    store: TileStore
    sets_dir: Path
    token: str
    allowed_origin: str = DEFAULT_ORIGIN
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr, flush=True)


def make_handler(cfg: SinkConfig) -> type[BaseHTTPRequestHandler]:
    class SinkHandler(BaseHTTPRequestHandler):
        server_version = "amap-sink/1"

        # --- plumbing -------------------------------------------------------
        def log_message(self, format: str, *args: Any) -> None:
            return  # requests are logged explicitly below

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", cfg.allowed_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-Sink-Token, X-SHA256"
            )
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self) -> bool:
            if self.headers.get("X-Sink-Token") == cfg.token:
                return True
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "missing or bad token"})
            return False

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_TILE_BYTES:
                raise TileError(f"bad Content-Length {length}")
            return self.rfile.read(length)

        # --- routes -----------------------------------------------------------
        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            if not self._authorised():
                return
            url = urlsplit(self.path)
            if url.path == "/health":
                self._json(HTTPStatus.OK, {"ok": True})
                return
            if url.path == "/queue":
                name = parse_qs(url.query).get("set", [""])[0]
                try:
                    scenes = read_scene_set(cfg.sets_dir, name)
                except TileError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                missing = cfg.store.missing(scenes)
                self._json(
                    HTTPStatus.OK,
                    {"set": name, "scenes": scenes, "missing": missing},
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorised():
                return
            url = urlsplit(self.path)
            try:
                if url.path == "/log":
                    cfg.log(f"[browser] {self._body()[:500].decode(errors='replace')}")
                    self._json(HTTPStatus.OK, {"ok": True})
                    return
                match = _TILE_PATH_RE.fullmatch(url.path)
                if match is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                tile = cfg.store.save(
                    match["scene"],
                    match["face"],
                    self._body(),
                    self.headers.get("X-SHA256", ""),
                )
            except TileError as exc:
                cfg.log(f"[sink] rejected {url.path}: {exc}")
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            cfg.log(f"[sink] saved {tile.scene}/{tile.face} ({tile.size_bytes} B)")
            self._json(HTTPStatus.OK, {"saved": f"{tile.scene}/{tile.face}"})

    return SinkHandler


def make_server(cfg: SinkConfig, host: str, port: int) -> ThreadingHTTPServer:
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"sink must bind to loopback, got {host!r}")
    server = ThreadingHTTPServer((host, port), make_handler(cfg))
    server.daemon_threads = True
    return server
