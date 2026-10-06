import hashlib
import io
import json
from collections.abc import Callable

import pytest
from PIL import Image

from amap_pipeline.acquire.store import FACES, TileError, TileStore, verify


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _non_square_jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 16), (10, 20, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_tile_store_save_valid_jpeg_writes_file_and_manifest(
    tile_store: TileStore, jpeg_bytes: bytes
) -> None:
    tile = tile_store.save("scene_1", "f", jpeg_bytes, _sha(jpeg_bytes))
    path = tile_store.tiles_dir / "scene_1" / "f.jpg"
    assert path.read_bytes() == jpeg_bytes, "Saved bytes differ from input"
    record = json.loads(tile_store.manifest.read_text().splitlines()[-1])
    assert record["sha256"] == tile.sha256, f"Manifest mismatch: {record}"
    leftovers = list(path.parent.glob("*.part"))
    assert leftovers == [], f"Temp files left behind: {leftovers}"


def test_tile_store_save_sha_mismatch_raises_tile_error(
    tile_store: TileStore, jpeg_bytes: bytes
) -> None:
    with pytest.raises(TileError, match="sha256"):
        tile_store.save("scene_1", "f", jpeg_bytes, "0" * 64)
    assert not tile_store.has("scene_1", "f"), "Rejected tile must not be stored"


@pytest.mark.parametrize(
    ("kind", "match"),
    [
        ("garbage", "SOI/EOI"),
        ("truncated", "decode"),
        ("too_small", "too small"),
        ("not_square", "not square"),
    ],
)
def test_tile_store_save_bad_image_raises_tile_error(
    tile_store: TileStore, jpeg_factory: Callable[..., bytes], kind: str, match: str
) -> None:
    data = {
        "garbage": b"not a jpeg",
        "truncated": jpeg_factory()[:-200] + b"\xff\xd9",
        "too_small": jpeg_factory(size=8),
        "not_square": _non_square_jpeg(),
    }[kind]
    with pytest.raises(TileError, match=match):
        tile_store.save("scene_1", "f", data, _sha(data))


@pytest.mark.parametrize(
    ("scene", "face"),
    [("../etc", "f"), ("scene_1/../../x", "f"), ("scene_1", "x"), ("scene_1", "../f")],
)
def test_tile_store_path_traversal_raises_tile_error(
    tile_store: TileStore, scene: str, face: str
) -> None:
    with pytest.raises(TileError):
        tile_store.path_for(scene, face)


def test_tile_store_missing_after_partial_save_resumes(
    tile_store: TileStore, jpeg_bytes: bytes
) -> None:
    tile_store.save("scene_1", "f", jpeg_bytes, _sha(jpeg_bytes))
    missing = tile_store.missing(["scene_1", "scene_2"])
    assert ("scene_1", "f") not in missing, "Saved face must not be re-queued"
    assert len(missing) == 2 * len(FACES) - 1, f"Unexpected queue length {missing}"


def test_verify_complete_and_missing_scenes_reported(
    tile_store: TileStore, jpeg_bytes: bytes
) -> None:
    for face in FACES:
        tile_store.save("scene_1", face, jpeg_bytes, _sha(jpeg_bytes))
    report = verify(tile_store, ["scene_1", "scene_2"])
    assert report.complete == ["scene_1"], f"Got {report.complete}"
    assert len(report.missing) == len(FACES), f"Got {report.missing}"
    assert not report.ok, "Report with missing faces must not be ok"


def test_verify_corrupt_file_on_disk_reported(
    tile_store: TileStore, jpeg_bytes: bytes
) -> None:
    for face in FACES:
        tile_store.save("scene_1", face, jpeg_bytes, _sha(jpeg_bytes))
    (tile_store.tiles_dir / "scene_1" / "u.jpg").write_bytes(b"garbage")
    report = verify(tile_store, ["scene_1"])
    assert [(s, f) for s, f, _ in report.corrupt] == [("scene_1", "u")], (
        f"Got {report.corrupt}"
    )


def test_tile_store_save_larger_face_records_its_size(
    tile_store: TileStore, jpeg_factory: Callable[..., bytes]
) -> None:
    data = jpeg_factory(size=32)
    tile = tile_store.save("scene_1", "f", data, _sha(data))
    assert tile.face_px == 32, f"Expected 32 px, got {tile.face_px}"
