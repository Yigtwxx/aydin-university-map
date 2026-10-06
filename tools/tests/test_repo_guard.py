from pathlib import Path

import pytest

from tools.repo_guard import MAX_BYTES, check_paths


@pytest.mark.parametrize(
    "path",
    [
        "data/raw/tour_scenes.json",
        "data/tiles/scene_1/f.jpg",
        "pipeline/out/campus.glb",
        "apps/web/src/pano.jpg",
    ],
)
def test_check_paths_forbidden_file_reports_violation(
    path: str, tmp_path: Path
) -> None:
    violations = check_paths([path], tmp_path)
    assert len(violations) == 1, f"Expected a violation for {path}, got {violations}"


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "pipeline/src/amap_pipeline/cli.py",
        "packages/contracts/fixtures/tiny.png",
        "apps/web/public/favicon.png",
    ],
)
def test_check_paths_allowed_file_passes(path: str, tmp_path: Path) -> None:
    assert check_paths([path], tmp_path) == [], f"{path} should be allowed"


def test_check_paths_oversized_file_reports_violation(tmp_path: Path) -> None:
    (tmp_path / "big.json").write_bytes(b"0" * (MAX_BYTES + 1))
    violations = check_paths(["big.json"], tmp_path)
    assert [v.path for v in violations] == ["big.json"], f"Got {violations}"


def test_check_paths_lockfile_is_size_exempt(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_bytes(b"0" * (MAX_BYTES + 1))
    assert check_paths(["uv.lock"], tmp_path) == [], "Lockfiles are size exempt"
