import json
from pathlib import Path

import pytest
from shapely.geometry import box

from amap_pipeline.geo.building_style import classify
from amap_pipeline.geo.osm import Building, LocalProjector
from amap_pipeline.geo.overrides import (
    DEFAULT_BUILDING_OVERRIDES,
    DEFAULT_POSE_OVERRIDES,
    DEFAULT_SCENE_OVERRIDES,
    BuildingOverrides,
    PoseOverride,
    SurveyPose,
    apply_building_overrides,
    apply_pose_overrides,
    apply_scene_fixes,
    apply_survey_poses,
    load_building_overrides,
    load_pose_overrides,
    load_scene_blocks,
    load_scene_fixes,
    load_survey_poses,
)

CONFIG = """
[names]
"way/2" = "Örnek Hastanesi"

[[add]]
id = "manual/x-blok"
name = "İstanbul Aydın Üniversitesi X Binası"
levels = 5
outline = [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]]
"""


def _building(osm_id: str, name: str | None = None) -> Building:
    return Building(osm_id=osm_id, name=name, levels=None, outline=box(0, 0, 5, 5))


def test_load_reads_names_and_added_buildings(tmp_path: Path) -> None:
    path = tmp_path / "overrides.toml"
    path.write_text(CONFIG, encoding="utf-8")
    overrides = load_building_overrides(path)
    assert overrides.names == {"way/2": "Örnek Hastanesi"}
    (added,) = overrides.added
    assert added.osm_id == "manual/x-blok"
    assert added.levels == 5
    assert added.outline.area == pytest.approx(80.0)


def test_load_missing_file_changes_nothing(tmp_path: Path) -> None:
    overrides = load_building_overrides(tmp_path / "absent.toml")
    assert overrides == BuildingOverrides(names={}, added=[])


def test_load_rejects_invalid_outline(tmp_path: Path) -> None:
    path = tmp_path / "overrides.toml"
    path.write_text(
        '[[add]]\nid = "manual/bad"\nname = "Bad"\n'
        "outline = [[0.0, 0.0], [1.0, 1.0]]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="manual/bad"):
        load_building_overrides(path)


def test_apply_renames_and_appends_without_touching_others() -> None:
    added = _building("manual/x-blok", "İstanbul Aydın Üniversitesi X Binası")
    overrides = BuildingOverrides(names={"way/2": "Örnek Hastanesi"}, added=[added])
    result = apply_building_overrides(
        [_building("way/1", "Kept"), _building("way/2")], overrides
    )
    assert [(b.osm_id, b.name) for b in result] == [
        ("way/1", "Kept"),
        ("way/2", "Örnek Hastanesi"),
        ("manual/x-blok", "İstanbul Aydın Üniversitesi X Binası"),
    ]


def test_load_reads_tags_of_added_buildings(tmp_path: Path) -> None:
    path = tmp_path / "overrides.toml"
    path.write_text(
        '[[add]]\nid = "manual/k"\nname = "Kiosk"\ntags = { building = "kiosk" }\n'
        "outline = [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]]\n",
        encoding="utf-8",
    )
    (kiosk,) = load_building_overrides(path).added
    assert kiosk.tags == {"building": "kiosk"}
    assert classify(kiosk) == "retail"


def test_default_config_adds_the_coffee_shop_and_names_the_hospital() -> None:
    overrides = load_building_overrides(DEFAULT_BUILDING_OVERRIDES)
    shop = next(b for b in overrides.added if b.osm_id == "manual/coffee-shop")
    assert classify(shop) == "retail", "a glass café pavilion, not a campus block"
    assert shop.outline.is_valid
    hospital = _building("way/1548069810", overrides.names["way/1548069810"])
    assert classify(hospital) == "hospital"


@pytest.mark.parametrize(
    ("osm_id", "letter"), [("way/539867979", "E"), ("way/539867978", "F")]
)
def test_default_config_names_e_and_f_blok(osm_id: str, letter: str) -> None:
    name = load_building_overrides(DEFAULT_BUILDING_OVERRIDES).names[osm_id]
    assert f" {letter} Binası" in name, f"{osm_id} should be {letter} Blok: {name}"
    assert classify(_building(osm_id, name)) == "campus"


POSES = """
[poses.scene_1]
x = 10.0
y = -5.0
heading_deg = 270.0
"""


def _record(x: float, y: float) -> dict[str, float]:
    return {"lat": 0.0, "lng": 0.0, "x": x, "y": y, "height_m": 1.6, "heading_deg": 0}


def test_load_pose_overrides_reads_position_and_heading(tmp_path: Path) -> None:
    path = tmp_path / "poses.toml"
    path.write_text(POSES, encoding="utf-8")
    assert load_pose_overrides(path) == {
        "scene_1": PoseOverride(x=10.0, y=-5.0, heading_deg=270.0)
    }


def test_apply_pose_overrides_moves_scene_and_marks_it_manual() -> None:
    projector = LocalProjector()
    posed = {"scene_1": _record(40.0, 40.0), "scene_2": _record(1.0, 2.0)}
    result = apply_pose_overrides(
        posed, {"scene_1": PoseOverride(10.0, -5.0, 270.0)}, projector
    )
    moved = result["scene_1"]
    assert (moved["x"], moved["y"], moved["heading_deg"]) == (10.0, -5.0, 270.0)
    assert moved["pose_source"] == "manual"
    assert moved["height_m"] == 1.6, "camera height is still the measured one"
    lng, lat = projector.to_wgs84(10.0, -5.0)
    assert (moved["lng"], moved["lat"]) == pytest.approx((lng, lat))
    assert result["scene_2"] == posed["scene_2"]
    assert posed["scene_1"]["x"] == 40.0, "input must not be mutated"


def test_apply_pose_overrides_rejects_unposed_scene() -> None:
    with pytest.raises(ValueError, match="scene_9"):
        apply_pose_overrides(
            {}, {"scene_9": PoseOverride(0.0, 0.0, 0.0)}, LocalProjector()
        )


def test_default_pose_overrides_parse() -> None:
    # Every hand pose moved into the survey notebooks (ADR-0010).
    overrides = load_pose_overrides(DEFAULT_POSE_OVERRIDES)
    assert all(0.0 <= o.heading_deg < 360.0 for o in overrides.values())


def test_load_survey_poses_marks_evidence(tmp_path: Path) -> None:
    path = tmp_path / "survey.json"
    path.write_text(
        json.dumps(
            {
                "poses": {
                    "scene_1": {
                        "x": 1,
                        "y": 2,
                        "z": 1.6,
                        "heading_deg": 370,
                        "free": False,
                        "sightings": 3,
                    },
                    "scene_2": {
                        "x": 3,
                        "y": 4,
                        "z": 1.6,
                        "heading_deg": 10,
                        "free": False,
                        "sightings": 0,
                    },
                    "scene_3": {
                        "x": 5,
                        "y": 6,
                        "z": 2.0,
                        "heading_deg": 20,
                        "free": True,
                        "sightings": 0,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    poses = load_survey_poses(path)
    assert poses["scene_1"] == SurveyPose(1.0, 2.0, 1.6, 10.0, True, sightings=3)
    assert not poses["scene_2"].surveyed  # only its model moved it
    assert poses["scene_3"].surveyed
    assert load_survey_poses(tmp_path / "absent.json") == {}


def test_apply_survey_poses_moves_and_adds_scenes() -> None:
    projector = LocalProjector()
    posed = {"scene_1": {"x": 0.0, "y": 0.0, "height_m": 1.9, "heading_deg": 0.0}}
    result = apply_survey_poses(
        posed,
        {
            "scene_1": SurveyPose(10.0, 0.0, 1.6, 90.0, True),
            "scene_2": SurveyPose(0.0, 10.0, 2.4, 45.0, False, sightings=3),
            "scene_3": SurveyPose(5.0, 5.0, 2.4, 45.0, True, sightings=0),
        },
        projector,
    )
    assert result["scene_1"]["x"] == 10.0
    assert result["scene_1"]["height_m"] == 1.9  # measured height stays
    assert result["scene_1"]["pose_source"] == "surveyed"
    assert result["scene_2"]["height_m"] == 2.4
    assert result["scene_2"]["pose_source"] == "sfm"
    assert "scene_3" not in result  # a guess without sightings stays out
    lng, lat = projector.to_wgs84(10.0, 0.0)
    assert (result["scene_1"]["lng"], result["scene_1"]["lat"]) == pytest.approx(
        (lng, lat)
    )
    assert posed["scene_1"]["x"] == 0.0  # input untouched


SCENE_FIXES = """
[blocks]
door_b = "D"

[scenes.door]
kind = "entrance"
label = { tr = "X Blok Girişi", en = "X Block Entrance" }
area = { tr = "X Blok", en = "X Block" }
block = "X"

[scenes.square]
kind = "outdoor"
label = { tr = "Kampüs", en = "Campus" }
"""


def _scene(name: str, kind: str, label: str) -> dict[str, object]:
    return {
        "name": name,
        "kind": kind,
        "label": {"tr": label, "en": label},
        "area": {"tr": "Kampüs", "en": "Campus"},
    }


def test_scene_fixes_move_an_entrance_to_the_door_panorama(tmp_path: Path) -> None:
    path = tmp_path / "scene_overrides.toml"
    path.write_text(SCENE_FIXES, encoding="utf-8")
    scenes = {
        "door": _scene("door", "outdoor", "Kampüs"),
        "square": _scene("square", "entrance", "X Blok Girişi"),
        "door_b": _scene("door_b", "entrance", "Giriş"),
        "other": _scene("other", "outdoor", "Kampüs"),
    }
    fixed = apply_scene_fixes(
        scenes, load_scene_fixes(path), blocks=load_scene_blocks(path)
    )
    assert fixed["door"]["kind"] == "entrance"
    assert fixed["door"]["label"] == {"tr": "X Blok Girişi", "en": "X Block Entrance"}
    assert fixed["door"]["area"] == {"tr": "X Blok", "en": "X Block"}
    assert fixed["door"]["block"] == "X"
    assert fixed["square"]["kind"] == "outdoor"
    assert fixed["square"]["label"]["tr"] == "Kampüs"
    assert fixed["door_b"]["block"] == "D"
    assert fixed["other"] == scenes["other"]
    assert scenes["door"]["kind"] == "outdoor"  # the input is not changed


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("[scenes.a]\nfloor = 2\n", "unknown scene fields"),
        ('[scenes.a]\nkind = "door"\n', "kind must be one of"),
        ('[scenes.a]\nlabel = { tr = "A" }\n', "label needs exactly tr and en"),
    ],
)
def test_scene_fixes_reject_bad_entries(
    tmp_path: Path, body: str, message: str
) -> None:
    path = tmp_path / "scene_overrides.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_scene_fixes(path)


def test_scene_fixes_reject_unknown_scene() -> None:
    with pytest.raises(ValueError, match="does not have"):
        apply_scene_fixes({}, {"ghost": {"kind": "outdoor"}})


def test_default_scene_fixes_put_a_blok_entrance_at_its_door() -> None:
    fixes = load_scene_fixes(DEFAULT_SCENE_OVERRIDES)
    door = fixes["scene_428526"]
    assert door["kind"] == "entrance"
    assert door["label"]["tr"] == "A Blok Girişi"
    assert door["block"] == "A"
    assert fixes["scene_428525"]["kind"] == "outdoor"
    # Exactly one panorama carries the name.
    named = [
        scene
        for scene, fix in fixes.items()
        if fix.get("label", {}).get("tr") == "A Blok Girişi"
    ]
    assert named == ["scene_428526"]
