from datetime import date
from pathlib import Path

import pytest

from amap_pipeline.export.pois import build_pois, read_poi_config

CONFIG = """
[[poi]]
id = "burger-king"
name = { tr = "Burger King", en = "Burger King" }
category = "food"
aliases = ["bk"]
node = "scene_1"
landmark = "poi.burger-king"
verified = { checked = 2026-10-07, status = "open", source = "https://example.com" }

[[poi]]
id = "atm"
name = { tr = "ATM", en = "Cash machine" }
category = "atm"
node = "scene_2"
own_panorama = false
pin = [1.0, 2.0]

[[poi]]
id = "ghost"
name = { tr = "Hayalet", en = "Ghost" }
category = "cafe"
node = "scene_9"
landmark = "poi.ghost"
"""


def test_pins_come_from_survey_tie_points(tmp_path: Path) -> None:
    path = tmp_path / "pois.toml"
    path.write_text(CONFIG, encoding="utf-8")
    nodes = {
        "scene_1": {"enu": [5.0, 5.0, 1.6], "anchor": "scene_3"},
        "scene_2": {"enu": [8.0, 9.0, 1.6], "anchor": None},
        "scene_3": {"enu": [4.0, 4.0, 1.6], "anchor": None},
    }
    collection, warnings = build_pois(
        read_poi_config(path),
        {"poi.burger-king": {"x": 12.345, "y": -3.0}},
        nodes,
    )
    pois = {p.id: p for p in collection.pois}
    assert pois["burger-king"].pin_enu == (12.35, -3.0)
    assert pois["burger-king"].pin_source == "storefront"
    assert pois["burger-king"].verified is not None
    assert pois["burger-king"].verified.checked == date(2026, 10, 7)
    assert pois["atm"].pin_enu == (1.0, 2.0)
    assert not pois["atm"].own_panorama
    assert pois["atm"].pin_source == "manual"
    assert pois["ghost"].pin_enu is None
    assert warnings == [
        "ghost: panorama scene_9 is not in the walking graph",
        "ghost: storefront poi.ghost not measured",
    ]


def test_duplicate_ids_are_rejected() -> None:
    entry = {
        "id": "x",
        "name": {"tr": "X", "en": "X"},
        "category": "cafe",
        "pin": [0, 0],
    }
    with pytest.raises(ValueError, match="duplicate"):
        build_pois([entry, entry], {}, {})


def test_missing_config_means_no_pois(tmp_path: Path) -> None:
    assert read_poi_config(tmp_path / "absent.toml") == []


def test_unmeasured_indoor_poi_is_pinned_at_its_door() -> None:
    entry = {
        "id": "kantin",
        "name": {"tr": "Kantin", "en": "Canteen"},
        "category": "food",
        "node": "scene_room",
        "landmark": "poi.kantin",
    }
    nodes = {
        "scene_room": {"enu": [0.0, 0.0, 1.6], "anchor": "scene_door"},
        "scene_door": {"enu": [7.5, -2.25, 1.6], "anchor": None},
    }
    collection, warnings = build_pois([entry], {}, nodes)
    (poi,) = collection.pois
    assert poi.pin_enu == (7.5, -2.25)
    assert poi.pin_source == "entrance"
    assert warnings == ["kantin: storefront poi.kantin not measured"]
