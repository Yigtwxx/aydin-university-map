from pathlib import Path

import pytest

from amap_pipeline.tour import Scene, SceneKind, classify, florya_scenes, load_overrides


def _by_name(scenes: list[Scene], name: str) -> Scene:
    return next(s for s in scenes if s.name == name)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("scene_900001", SceneKind.OUTDOOR),  # Kampüs
        ("scene_900004", SceneKind.OUTDOOR),  # Otopark
        ("scene_900005", SceneKind.OUTDOOR),  # T Blok Bahçe
        ("scene_900006", SceneKind.ENTRANCE),  # A Blok Girişi
        ("scene_900007", SceneKind.INDOOR),  # A Blok 1.Kat
        ("scene_900008", SceneKind.INDOOR),  # Kafe - Giriş Kat (ground floor)
        ("scene_900012", SceneKind.ENTRANCE),  # KÜTÜPHANE GİRİŞ (upper case)
        ("scene_900010", SceneKind.INDOOR),  # no metadata
    ],
)
def test_classify_keyword_rules_assign_expected_kind(
    scenes: list[Scene], name: str, expected: SceneKind
) -> None:
    result = classify(_by_name(scenes, name))
    assert result is expected, f"{name}: expected {expected}, got {result}"


def test_classify_override_wins_over_keywords(scenes: list[Scene]) -> None:
    result = classify(
        _by_name(scenes, "scene_900007"), {"scene_900007": SceneKind.OUTDOOR}
    )
    assert result is SceneKind.OUTDOOR, f"Override ignored, got {result}"


def test_florya_scenes_drops_other_campus_and_missing_meta(scenes: list[Scene]) -> None:
    names = {s.name for s in florya_scenes(scenes)}
    assert "scene_900009" not in names, "Other-campus scene must be dropped"
    assert "scene_900010" not in names, "Scene without metadata must be dropped"
    assert len(names) == 10, f"Expected 10 Florya scenes, got {len(names)}"


def test_load_overrides_toml_table_returns_kinds(tmp_path: Path) -> None:
    path = tmp_path / "overrides.toml"
    path.write_text('[overrides]\nscene_1 = "entrance"\n', encoding="utf-8")
    assert load_overrides(path) == {"scene_1": SceneKind.ENTRANCE}


def test_load_overrides_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_overrides(tmp_path / "nope.toml") == {}


def test_load_overrides_unknown_kind_raises_value_error(tmp_path: Path) -> None:
    path = tmp_path / "overrides.toml"
    path.write_text('[overrides]\nscene_1 = "roof"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_overrides(path)
