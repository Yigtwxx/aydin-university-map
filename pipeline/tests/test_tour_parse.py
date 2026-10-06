import pytest

from amap_pipeline.tour import Scene
from amap_pipeline.tour.parse import parse_meta, parse_place_code

_REAL_SHAPE = (
    "sceneacildi(428111,get(panorama),get(onceki)); "
    "hedefibelirle(428523,4,92,174,251,352,0,0,524,522,506,528,0,0,42,133,213,302,"
    "0,0,99,199,250,43,0,0,40.991470,28.797111,355,501,501,Kampüs,Florya Kampüs,"
    "Florya Campus,Campus);"
)


def test_parse_meta_real_shaped_onstart_decodes_coords_and_labels() -> None:
    meta = parse_meta(_REAL_SHAPE)
    assert meta is not None, "Expected metadata"
    assert (meta.lat, meta.lng) == (40.991470, 28.797111), f"Got {meta.lat, meta.lng}"
    assert meta.angle_p28 == 355.0, f"Got {meta.angle_p28}"
    assert meta.place_group == "501", f"Got {meta.place_group}"
    assert (meta.label_tr, meta.area_tr, meta.area_en, meta.label_en) == (
        "Kampüs",
        "Florya Kampüs",
        "Florya Campus",
        "Campus",
    ), f"Got labels {meta}"


def test_parse_meta_comma_in_english_label_joins_tail() -> None:
    onstart = _REAL_SHAPE.replace(
        "Kampüs,Florya Kampüs,Florya Campus,Campus",
        "Al Götür Oku Getir,Kütüphane,Library,Take it, Read it, Bring it",
    )
    meta = parse_meta(onstart)
    assert meta is not None, "Expected metadata"
    assert meta.label_en == "Take it, Read it, Bring it", f"Got {meta.label_en!r}"
    assert meta.area_en == "Library", f"Got {meta.area_en!r}"


@pytest.mark.parametrize(
    "onstart",
    [
        "mekanibelirle(901); sceneacildi(428101,get(panorama),get(onceki));",
        "hedefibelirle(1,2,3);",
        _REAL_SHAPE.replace("40.991470", "abc"),
    ],
)
def test_parse_meta_missing_or_invalid_returns_none(onstart: str) -> None:
    assert parse_meta(onstart) is None, f"Expected None for {onstart!r}"


def test_parse_place_code_present_returns_code() -> None:
    assert parse_place_code("mekanibelirle(941); x();") == "941"


def test_parse_scene_hotspots_keep_links_and_angles(scenes: list[Scene]) -> None:
    hub = scenes[0]
    assert hub.nav_links == ("scene_900002", "scene_900003"), f"Got {hub.nav_links}"
    assert hub.hotspots[1].ath == 90.0, f"Got {hub.hotspots[1].ath}"
    assert hub.hotspots[1].arrival_heading == 45.0, f"Got {hub.hotspots[1]}"


def test_parse_scene_without_metadata_has_place_code(scenes: list[Scene]) -> None:
    no_meta = next(s for s in scenes if s.name == "scene_900010")
    assert no_meta.meta is None, "Scene without hedefibelirle must have no meta"
    assert no_meta.place_code == "901", f"Got {no_meta.place_code}"
