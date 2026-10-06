"""Validated, resumable on-disk store for cube-face tiles.

Layout: ``<tiles_dir>/<scene>/<face>.jpg`` plus an append-only
``<tiles_dir>/manifest.jsonl``. Writes are atomic (temp file + rename), so an
interrupted export never leaves a half-written face behind.
"""

import hashlib
import io
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

FACES: tuple[str, ...] = ("f", "r", "b", "l", "u", "d")
FACE_SIZE = 1300
MAX_TILE_BYTES = 8_000_000
_SCENE_RE = re.compile(r"^scene_\d{1,12}$")


class TileError(ValueError):
    """A tile was rejected; the message is safe to return to the client."""


@dataclass(frozen=True, slots=True)
class StoredTile:
    scene: str
    face: str
    sha256: str
    size_bytes: int


def validate_key(scene: str, face: str) -> None:
    if not _SCENE_RE.fullmatch(scene):
        raise TileError(f"invalid scene name {scene!r}")
    if face not in FACES:
        raise TileError(f"invalid face {face!r}")


def check_jpeg(data: bytes, expected_size: int) -> None:
    """Reject anything that is not a complete JPEG of the expected square size."""
    if len(data) > MAX_TILE_BYTES:
        raise TileError(f"tile too large ({len(data)} bytes)")
    if not (
        data.startswith(b"\xff\xd8") and data.rstrip(b"\x00").endswith(b"\xff\xd9")
    ):
        raise TileError("not a complete JPEG (missing SOI/EOI marker)")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            size = img.size
    except Exception as exc:  # Pillow raises many error types for bad data
        raise TileError(f"JPEG does not decode: {exc}") from exc
    if size != (expected_size, expected_size):
        raise TileError(f"unexpected size {size}, want {expected_size}x{expected_size}")


class TileStore:
    def __init__(self, tiles_dir: Path, face_size: int = FACE_SIZE) -> None:
        self.tiles_dir = tiles_dir
        self.face_size = face_size
        self.manifest = tiles_dir / "manifest.jsonl"
        tiles_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, scene: str, face: str) -> Path:
        validate_key(scene, face)
        return self.tiles_dir / scene / f"{face}.jpg"

    def has(self, scene: str, face: str) -> bool:
        return self.path_for(scene, face).is_file()

    def missing(self, scenes: list[str]) -> list[tuple[str, str]]:
        """Faces still to fetch for ``scenes``, in scene order (resume support)."""
        return [(s, f) for s in scenes for f in FACES if not self.has(s, f)]

    def save(self, scene: str, face: str, data: bytes, sha256_hex: str) -> StoredTile:
        target = self.path_for(scene, face)
        digest = hashlib.sha256(data).hexdigest()
        if digest != sha256_hex.strip().lower():
            raise TileError("sha256 mismatch")
        check_jpeg(data, self.face_size)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        tile = StoredTile(scene, face, digest, len(data))
        self._append_manifest(tile)
        return tile

    def _append_manifest(self, tile: StoredTile) -> None:
        record = {
            "scene": tile.scene,
            "face": tile.face,
            "sha256": tile.sha256,
            "bytes": tile.size_bytes,
            "received_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        with self.manifest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


@dataclass(frozen=True, slots=True)
class VerifyReport:
    complete: list[str]
    missing: list[tuple[str, str]]
    corrupt: list[tuple[str, str, str]]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.corrupt


def verify(store: TileStore, scenes: list[str]) -> VerifyReport:
    complete: list[str] = []
    missing: list[tuple[str, str]] = []
    corrupt: list[tuple[str, str, str]] = []
    for scene in scenes:
        scene_ok = True
        for face in FACES:
            path = store.path_for(scene, face)
            if not path.is_file():
                missing.append((scene, face))
                scene_ok = False
                continue
            try:
                check_jpeg(path.read_bytes(), store.face_size)
            except TileError as exc:
                corrupt.append((scene, face, str(exc)))
                scene_ok = False
        if scene_ok:
            complete.append(scene)
    return VerifyReport(complete, missing, corrupt)
