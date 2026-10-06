"""Place grouping and Turkish-aware search shared by the API and the loader."""

import pytest

from amap_contracts.graph import LocalizedText, Node, NodeKind, PoseSource
from amap_contracts.places import build_places, search_places


def _node(node_id: str, tr: str, en: str, kind: NodeKind) -> Node:
    return Node(
        id=node_id,
        kind=kind,
        lat=40.9915,
        lng=28.7971,
        alt_m=1.6,
        enu=(0.0, 0.0, 1.6),
        heading_deg=0.0,
        pose_source=PoseSource.SFM,
        label=LocalizedText(tr=tr, en=en),
        area=LocalizedText(tr="Florya Kampüs", en="Florya Campus"),
        building=tr[0] if "Blok" in tr else None,
    )


@pytest.fixture
def places() -> list:
    return build_places(
        [
            _node("a1", "A Blok Girişi", "A Block Entrance", NodeKind.ENTRANCE),
            _node("b1", "B Blok Giriş", "B Block Entrance", NodeKind.ENTRANCE),
            _node("e1", "E Blok Giriş", "E Block Entrance", NodeKind.ENTRANCE),
            _node("k1", "Kütüphane Giriş", "Library Entrance", NodeKind.ENTRANCE),
            _node("c1", "Kampüs", "Campus", NodeKind.OUTDOOR),
            _node("c2", "Kampüs", "Campus", NodeKind.OUTDOOR),
        ]
    )


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("a blok", ["A Blok Girişi"]),
        ("b blok", ["B Blok Giriş"]),
        ("e blok", ["E Blok Giriş"]),
        ("KÜTÜPHANE", ["Kütüphane Giriş"]),
        ("library", ["Kütüphane Giriş"]),
    ],
)
def test_search_places_single_letter_is_a_whole_block_code(
    places: list, query: str, expected: list[str]
) -> None:
    found = [p.name_tr for p in search_places(places, query)]
    assert found == expected, f"{query!r} -> {found}"


def test_build_places_groups_panoramas_by_label(places: list) -> None:
    campus = next(p for p in places if p.name_tr == "Kampüs")
    assert campus.node_ids == ("c1", "c2"), "same label shares one place"
    assert campus.id == "c1", "the first node id represents the place"


def test_search_places_lists_entrances_before_open_areas(places: list) -> None:
    found = [p.kind for p in search_places(places, "giris")]
    assert found and all(k is NodeKind.ENTRANCE for k in found), found


def test_search_places_empty_query_returns_nothing(places: list) -> None:
    assert search_places(places, "  ") == [], "blank query has no results"


def _room(
    node_id: str,
    tr: str,
    building: str | None,
    floor: int | None,
    area: str = "Sağlık Bilimleri",
    anchor: str | None = "door",
) -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.INDOOR,
        lat=40.9915,
        lng=28.7971,
        alt_m=1.6,
        enu=(0.0, 0.0, 1.6),
        heading_deg=0.0,
        pose_source=PoseSource.INTERPOLATED,
        label=LocalizedText(tr=tr, en=f"{tr} (en)"),
        area=LocalizedText(tr=area, en=area),
        building=building,
        floor=floor,
        anchor=anchor,
    )


@pytest.fixture
def rooms() -> list:
    return build_places(
        [
            _node("m1", "M Blok Giriş", "M Block Entrance", NodeKind.ENTRANCE),
            _node("c1", "Kampüs", "Campus", NodeKind.OUTDOOR),
            _room("r1", "Anatomi Lab", "M", 5),
            _room("r2", "Anatomi Lab", "M", 5),
            _room("d1", "Derslik", "D", 3, area="D Blok"),
            _room("d2", "Derslik", "M", 1, area="Florya Kampüs"),
            _room("k1", "Kampüs Koridoru", None, None, area="Florya Kampüs"),
        ]
    )


def test_build_places_rooms_group_by_label_block_and_floor(rooms: list) -> None:
    anatomy = [p for p in rooms if p.name_tr == "Anatomi Lab"]
    assert [p.node_ids for p in anatomy] == [("r1", "r2")], anatomy
    classrooms = [(p.building, p.floor) for p in rooms if p.name_tr == "Derslik"]
    assert classrooms == [("D", 3), ("M", 1)], "same name, different rooms"


def test_build_places_room_key_names_block_and_area(rooms: list) -> None:
    lab = next(p for p in rooms if p.name_tr == "Anatomi Lab")
    assert {"m", "blok", "saglik", "bilimleri"} <= set(lab.key.split()), lab.key
    hall = next(p for p in rooms if p.name_tr == "Kampüs Koridoru")
    assert "florya" not in hall.key, "the campus at large is no area"


def test_search_places_rooms_rank_after_entrances_and_open_areas(rooms: list) -> None:
    found = [p.kind for p in search_places(rooms, "m blok")]
    assert found[0] is NodeKind.ENTRANCE, found
    assert found[1:] and set(found[1:]) == {NodeKind.INDOOR}, found
    kinds = [p.kind for p in search_places(rooms, "kampus")]
    assert kinds == [NodeKind.OUTDOOR, NodeKind.INDOOR], kinds


def test_build_places_measured_panorama_represents_a_place() -> None:
    door = _node("z9", "T Blok Giriş", "T Block Entrance", NodeKind.ENTRANCE)
    borrowed = door.model_copy(update={"id": "a1", "anchor": "x"})
    (place,) = build_places([borrowed, door])
    assert place.id == "z9", "the measured door, not the borrowed one"
    assert place.node_ids == ("a1", "z9"), place.node_ids


def test_search_places_name_matches_beat_area_matches() -> None:
    places = build_places(
        [
            _room("a2", "Amfi - 2", "T", 4, area="T Blok Sınıflar"),
            _room("s2", "Sınıf - 2", "T", -2, area="T Blok Sınıflar"),
        ]
    )
    found = [p.name_tr for p in search_places(places, "sınıf 2 t blok")]
    assert found == ["Sınıf - 2", "Amfi - 2"], found


@pytest.mark.parametrize(
    ("label", "floor", "expected"),
    [
        ("T Blok -2.Kat", 2, True),  # the label says minus, the floor plus
        ("T Blok -2.Kat", -2, False),
        ("M Blok-4.Kat Koridor", 4, True),  # a glued hyphen reads as one too
        ("M Blok -5 Koridor", 5, True),
        ("T Blok 2.Kat", -2, True),
        ("T Blok 2.Kat", 2, False),
        ("Sınıf - 2", 2, False),  # a room number, not a floor
        ("Anatomi Lab", 5, False),
        ("Kütüphane 0.Kat", 0, False),
    ],
)
def test_spells_other_floor_catches_contradicting_labels(
    label: str, floor: int, expected: bool
) -> None:
    from amap_contracts.text import spells_other_floor

    assert spells_other_floor(label, floor) is expected, f"{label!r} {floor}"
