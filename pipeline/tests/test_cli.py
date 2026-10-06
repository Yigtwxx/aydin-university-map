import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from amap_pipeline.cli import app

runner = CliRunner()


@pytest.fixture
def data_root(dump_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = dump_path.parent.parent
    monkeypatch.setenv("AMAP_DATA_DIR", str(root))
    return root


def test_tour_build_writes_classified_scenes(data_root: Path) -> None:
    result = runner.invoke(app, ["tour", "build"])
    assert result.exit_code == 0, result.output
    records = json.loads((data_root / "derived" / "scenes.json").read_text("utf-8"))
    kinds = {r["name"]: r["kind"] for r in records}
    assert len(records) == 10, f"Expected 10 Florya scenes, got {len(records)}"
    assert kinds["scene_900006"] == "entrance", f"Got {kinds['scene_900006']}"
    assert kinds["scene_900008"] == "indoor", f"Got {kinds['scene_900008']}"


def test_tour_select_writes_outdoor_set(data_root: Path) -> None:
    result = runner.invoke(
        app, ["tour", "select", "--hub", "scene_900001", "--n", "4", "--name", "t4"]
    )
    assert result.exit_code == 0, result.output
    selected = (data_root / "derived" / "sets" / "t4.txt").read_text("utf-8").split()
    assert selected == [
        "scene_900001",
        "scene_900002",
        "scene_900003",
        "scene_900004",
    ], f"Got {selected}"
