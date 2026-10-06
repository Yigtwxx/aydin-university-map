import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from amap_pipeline.recon.sfm import (
    SfmConfig,
    scene_of,
    scene_pairs,
    stage_images,
    write_masks,
    write_pairs,
    write_workspace_rig,
)

CHAIN = {
    "scene_1": {"scene_2"},
    "scene_2": {"scene_1", "scene_3"},
    "scene_3": {"scene_2", "scene_4"},
    "scene_4": {"scene_3"},
}


@pytest.fixture
def cfg() -> SfmConfig:
    return SfmConfig(set="mini", run="test", face_px=16, faces=("f", "r", "d"))


@pytest.fixture
def tiles(tmp_path: Path, jpeg_factory: Callable[..., bytes]) -> Path:
    root = tmp_path / "tiles"
    for scene, size in (("scene_1", 16), ("scene_2", 12)):
        for face in ("f", "r", "b", "l", "u", "d"):
            path = root / scene / f"{face}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(jpeg_factory(size=size))
    return root


@pytest.mark.parametrize(
    ("hops", "expected"),
    [
        (1, [("scene_1", "scene_2"), ("scene_2", "scene_3"), ("scene_3", "scene_4")]),
        (
            2,
            [
                ("scene_1", "scene_2"),
                ("scene_1", "scene_3"),
                ("scene_2", "scene_3"),
                ("scene_2", "scene_4"),
                ("scene_3", "scene_4"),
            ],
        ),
    ],
)
def test_scene_pairs_hops_limit_neighbourhood(
    hops: int, expected: list[tuple[str, str]]
) -> None:
    result = scene_pairs(list(CHAIN), CHAIN, hops)
    assert result == expected, f"hops={hops}: got {result}"


def test_scene_pairs_ignore_scenes_outside_set() -> None:
    result = scene_pairs(["scene_1", "scene_3"], CHAIN, 2)
    assert result == [], f"Path through a missing scene must not pair, got {result}"


def test_write_pairs_all_face_combinations(tmp_path: Path) -> None:
    path = tmp_path / "pairs.txt"
    count = write_pairs(path, [("scene_1", "scene_2")], ("f", "r"))
    lines = path.read_text().splitlines()
    assert count == 4 == len(lines), f"Expected 4 pairs, got {lines}"
    assert "f/scene_1.jpg r/scene_2.jpg" in lines, f"Missing cross-face pair: {lines}"


def test_stage_images_symlinks_matching_and_resizes_others(
    tmp_path: Path, tiles: Path, cfg: SfmConfig
) -> None:
    images = tmp_path / "images"
    names = stage_images(["scene_1", "scene_2"], tiles, images, cfg)
    assert len(names) == 6, f"Expected 2 scenes x 3 faces, got {names}"
    assert (images / "f" / "scene_1.jpg").is_symlink(), "Same-size face must be linked"
    resized = images / "f" / "scene_2.jpg"
    assert not resized.is_symlink(), "Smaller face must be re-encoded"
    with Image.open(resized) as img:
        assert img.size == (16, 16), f"Resized to {img.size}"


def test_stage_images_applies_face_transform(
    tmp_path: Path, tiles: Path, cfg: SfmConfig
) -> None:
    flipped = replace(cfg, transforms={"f": "flip", "r": "id", "d": "id"})
    images = tmp_path / "images"
    stage_images(["scene_1"], tiles, images, flipped)
    assert not (images / "f" / "scene_1.jpg").is_symlink(), "Transformed face is a copy"


def test_write_masks_blocks_nadir_only(tmp_path: Path, cfg: SfmConfig) -> None:
    write_masks(["scene_1"], tmp_path, cfg)
    with Image.open(tmp_path / "d" / "scene_1.jpg.png") as nadir:
        assert nadir.getpixel((8, 8)) == 0, "Nadir centre must be masked"
        assert nadir.getpixel((0, 0)) == 255, "Nadir corner must stay open"
    with Image.open(tmp_path / "f" / "scene_1.jpg.png") as front:
        assert front.getpixel((8, 8)) == 255, "Side faces must stay open"


def test_write_workspace_rig_keeps_only_used_faces(
    tmp_path: Path, cfg: SfmConfig
) -> None:
    path = tmp_path / "rig.json"
    write_workspace_rig(path, cfg)
    prefixes = [c["image_prefix"] for c in json.loads(path.read_text())[0]["cameras"]]
    assert prefixes == ["f/", "r/", "d/"], f"Got {prefixes}"


def test_sfm_config_from_toml_reads_faces(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('[sfm]\nset = "s"\nrun = "r"\nfaces = ["f", "d"]\n', "utf-8")
    assert SfmConfig.from_toml(path).faces == ("f", "d")


@pytest.mark.parametrize(
    "body",
    ['faces = ["r", "d"]', 'faces = ["f", "x"]', 'mapper = "magic"'],
)
def test_sfm_config_from_toml_invalid_raises_value_error(
    tmp_path: Path, body: str
) -> None:
    path = tmp_path / "c.toml"
    path.write_text(f'[sfm]\nset = "s"\nrun = "r"\n{body}\n', "utf-8")
    with pytest.raises(ValueError):
        SfmConfig.from_toml(path)


def test_scene_of_image_name_returns_scene() -> None:
    assert scene_of("r/scene_428523.jpg") == "scene_428523"
