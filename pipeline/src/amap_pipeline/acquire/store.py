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
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageFile

FACES: tuple[str, ...] = ("f", "r", "b", "l", "u", "d")
# Faces vary per scene (most 1300 px, some 966 px); staging resizes them for SfM.
MIN_FACE_SIZE = 512
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
    face_px: int
    repaired: bool = False


def validate_key(scene: str, face: str) -> None:
    if not _SCENE_RE.fullmatch(scene):
        raise TileError(f"invalid scene name {scene!r}")
    if face not in FACES:
        raise TileError(f"invalid face {face!r}")


@dataclass(frozen=True, slots=True)
class JpegInfo:
    face_px: int
    truncated: bool  # the source file itself ends without an EOI marker


_SOI, _EOI = b"\xff\xd8", b"\xff\xd9"
# Pillow's truncated-image switch is process-global; the sink is multi-threaded.
_TRUNCATED_LOCK = threading.Lock()


def check_jpeg(data: bytes, min_size: int) -> JpegInfo:
    """Validate a square JPEG face; source-truncated files are reported, not rejected.

    Transfer integrity is guaranteed by the SHA-256 check, so a missing EOI
    marker means the tour's own file is truncated (seen once in 2,544 faces).
    """
    if len(data) > MAX_TILE_BYTES:
        raise TileError(f"tile too large ({len(data)} bytes)")
    if not data.startswith(_SOI):
        raise TileError("not a JPEG (missing SOI marker)")
    truncated = not data.rstrip(b"\x00").endswith(_EOI)
    try:
        with Image.open(io.BytesIO(data)) as img:
            size = img.size
            if not truncated:
                img.load()
    except Exception as exc:  # Pillow raises many error types for bad data
        raise TileError(f"JPEG does not decode: {exc}") from exc
    width, height = size
    if width != height:
        raise TileError(f"face is not square: {size}")
    if width < min_size:
        raise TileError(f"face too small: {width}px < {min_size}px")
    return JpegInfo(width, truncated)


def repair_truncated(data: bytes) -> bytes:
    """Decode a source-truncated JPEG (missing area becomes grey) and re-encode it."""
    with _TRUNCATED_LOCK:
        previous = ImageFile.LOAD_TRUNCATED_IMAGES
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            with Image.open(io.BytesIO(data)) as img:
                rgb = img.convert("RGB")
        except Exception as exc:
            raise TileError(f"truncated JPEG cannot be repaired: {exc}") from exc
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = previous
    out = io.BytesIO()
    rgb.save(out, format="JPEG", quality=95)
    return out.getvalue()


class TileStore:
    def __init__(self, tiles_dir: Path, min_face_size: int = MIN_FACE_SIZE) -> None:
        self.tiles_dir = tiles_dir
        self.min_face_size = min_face_size
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
        info = check_jpeg(data, self.min_face_size)
        if info.truncated:
            data = repair_truncated(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        tile = StoredTile(scene, face, digest, len(data), info.face_px, info.truncated)
        self._append_manifest(tile)
        return tile

    def _append_manifest(self, tile: StoredTile) -> None:
        record = {
            "scene": tile.scene,
            "face": tile.face,
            "sha256": tile.sha256,
            "bytes": tile.size_bytes,
            "face_px": tile.face_px,
            "repaired_truncated_source": tile.repaired,
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
                if check_jpeg(path.read_bytes(), store.min_face_size).truncated:
                    raise TileError("stored file is truncated")
            except TileError as exc:
                corrupt.append((scene, face, str(exc)))
                scene_ok = False
        if scene_ok:
            complete.append(scene)
    return VerifyReport(complete, missing, corrupt)
