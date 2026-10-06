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
