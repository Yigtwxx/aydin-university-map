import tomllib
from pathlib import Path

import pytest
from shapely.geometry import box

from amap_pipeline.export.assets import massing
from amap_pipeline.geo.campus import Registry, apply_campus, load_campus, parse_campus
from amap_pipeline.geo.osm import Building
from amap_pipeline.geo.overrides import BuildingOverrides, apply_building_overrides

OSM = [
    Building("way/1", "İstanbul Aydın Üniversitesi B Binası", None, box(0, 0, 40, 10)),
    Building("way/2", None, 3.0, box(50, 0, 70, 20)),
    Building("way/3", None, None, box(80, 0, 90, 10)),
]


def _registry(text: str) -> Registry:
    return parse_campus(tomllib.loads(text))


def test_block_names_and_measures_its_footprint() -> None:
    registry = _registry(
        """
[blocks.T]
name = { tr = "T Blok", en = "T Block" }
osm = ["way/2"]
levels = 5
height_m = 18.4
"""
    )
    (t,) = [b for b in apply_campus(OSM, registry) if b.osm_id == "way/2"]
    assert t.name == "İstanbul Aydın Üniversitesi T Binası"
    assert t.levels == 5
    assert t.registry == {
        "code": "T",
        "height_m": 18.4,
        "height_source": "pano",
        "levels": 5,
    }


def test_split_carves_a_part_out_of_its_parent() -> None:
    registry = _registry(
        """
[blocks.G]
split_from = "way/1"
outline = [[30.0, 0.0], [40.0, 0.0], [40.0, 10.0], [30.0, 10.0]]
"""
    )
    result = {b.osm_id: b for b in apply_campus(OSM, registry)}
    assert result["way/1"].outline.area == pytest.approx(300.0)
    assert result["campus/G"].outline.area == pytest.approx(100.0)
    assert result["campus/G"].name == "İstanbul Aydın Üniversitesi G Binası"


def test_outline_replaces_a_wrong_footprint_and_remove_drops_one() -> None:
    registry = _registry(
        """
remove = ["way/3"]

[blocks.D]
osm = ["way/2"]
outline = [
  [50.0, 0.0], [70.0, 0.0], [70.0, 20.0], [60.0, 20.0], [60.0, 10.0], [50.0, 10.0],
]
"""
    )
    result = {b.osm_id: b for b in apply_campus(OSM, registry)}
    assert result["way/2"].outline.area == pytest.approx(300.0)
    assert "way/3" not in result
    assert "campus/D" not in result


def test_non_letter_codes_keep_their_own_name() -> None:
    registry = _registry(
        """
[blocks.KUTUPHANE]
name = { tr = "Kütüphane", en = "Library" }
outline = [[0.0, 20.0], [10.0, 20.0], [10.0, 30.0], [0.0, 30.0]]
"""
    )
    library = apply_campus(OSM, registry)[-1]
    assert library.name == "İstanbul Aydın Üniversitesi Kütüphane"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[blocks.X]\nname = { tr = "X" }\n', "osm footprints or an outline"),
        ('[blocks.X]\nsplit_from = "way/1"\nosm = ["way/2"]\n', "needs the part"),
    ],
)
def test_invalid_blocks_are_rejected(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _registry(text)


def test_unknown_or_shared_footprints_are_rejected() -> None:
    with pytest.raises(ValueError, match="no footprint way/9"):
        apply_campus(OSM, _registry('[blocks.X]\nosm = ["way/9"]\n'))
    shared = '[blocks.X]\nosm = ["way/2"]\n[blocks.Y]\nosm = ["way/2"]\n'
    with pytest.raises(ValueError, match="belongs to"):
        apply_campus(OSM, _registry(shared))


def test_export_carries_code_height_and_facade() -> None:
    registry = _registry(
        """
[blocks.T]
osm = ["way/2"]
levels = 5
height_m = 18.4
base_m = 1.2
facade = { windows = "punched", wall = "#e8d9b0" }
"""
    )
    buildings = apply_building_overrides(
        OSM, BuildingOverrides(names={}, added=[]), registry
    )
    data = massing(buildings)
    (t,) = [f for f in data["buildings"] if f["id"] == "way/2"]
    assert t["campus"] and t["code"] == "T"
    assert (t["height_m"], t["levels"], t["height_source"]) == (18.4, 5, "pano")
    assert t["base_m"] == 1.2
    assert t["facade"]["windows"] == "punched"
    assert t["facade"]["wall"] == "#e8d9b0"
    assert t["facade"]["bay_m"] == 3.4  # defaults filled in


def test_missing_registry_changes_nothing(tmp_path: Path) -> None:
    assert load_campus(tmp_path / "absent.toml").blocks == {}


def test_invalid_facade_is_rejected() -> None:
    with pytest.raises(ValueError, match="block T: invalid facade"):
        _registry('[blocks.T]\nosm = ["way/2"]\nfacade = { wall = "ochre" }\n')
