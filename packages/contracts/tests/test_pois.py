"""Points of interest: validation and how they enrich searchable places."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from amap_contracts.graph import LocalizedText, Node, NodeKind, PoseSource
from amap_contracts.places import build_places, search_places
from amap_contracts.pois import (
    Poi,
    PoiCategory,
    PoiCollection,
    Verification,
    VerifyStatus,
)


def _node(node_id: str, tr: str, kind: NodeKind = NodeKind.INDOOR) -> Node:
    return Node(
        id=node_id,
        kind=kind,
        lat=40.9915,
        lng=28.7971,
        alt_m=1.6,
        enu=(0.0, 0.0, 1.6),
        heading_deg=0.0,
        pose_source=PoseSource.SFM,
        label=LocalizedText(tr=tr, en=tr),
        area=LocalizedText(tr="Kafe", en="Cafe"),
    )


def _poi(slug: str, node_id: str | None, **kw: object) -> Poi:
    return Poi.model_validate(
        {
            "id": slug,
            "name": {"tr": slug.title(), "en": slug.title()},
            "category": "food",
            "node_id": node_id,
            **kw,
        }
    )


NODES = [
    _node("scene_1", "Burger King"),
    _node("scene_2", "Kampüs", NodeKind.OUTDOOR),
]


def test_poi_ids_are_slugs() -> None:
    with pytest.raises(ValidationError):
        _poi("Burger King", "scene_1")


def test_poi_enriches_the_place_of_its_panorama() -> None:
    poi = _poi(
        "burger-king",
        "scene_1",
        brand="Burger King",
        aliases=("bk", "hamburger"),
        pin_enu=(12.5, -3.0),
        building="C",
        floor=0,
    )
    places = {p.id: p for p in build_places(NODES, [poi])}
    place = places["scene_1"]
    assert place.category == "food"
    assert place.pin_enu == (12.5, -3.0)
    assert place.building == "C"
    assert place.is_poi
    assert [p.id for p in search_places(list(places.values()), "bk")] == ["scene_1"]
    assert [p.id for p in search_places(list(places.values()), "hamburger")] == [
        "scene_1"
    ]


def test_poi_without_its_own_panorama_becomes_a_place() -> None:
    atm = _poi("atm-ziraat", "scene_2", category=PoiCategory.ATM, own_panorama=False)
    places = {p.id: p for p in build_places(NODES, [atm])}
    place = places["poi:atm-ziraat"]
    assert place.node_ids == ("scene_2",)
    assert place.kind is NodeKind.OUTDOOR
    assert place.category == "atm"
    assert places["scene_2"].category is None  # the open area stays itself


def test_poi_pointing_nowhere_is_dropped() -> None:
    places = build_places(NODES, [_poi("ghost", "scene_404")])
    assert all(p.id != "poi:ghost" for p in places)


def test_closed_poi_is_not_found() -> None:
    closed = _poi(
        "burger-king",
        "scene_1",
        verified=Verification(
            checked=date(2026, 10, 7), status=VerifyStatus.CLOSED, source="web"
        ),
    )
    places = build_places(NODES, [closed])
    assert not closed.listed
    assert search_places(places, "burger") == []


def test_collection_round_trips() -> None:
    collection = PoiCollection(
        generated_at=datetime(2026, 10, 7, tzinfo=UTC),
        pois=[_poi("starbucks", "scene_1", category="cafe")],
    )
    restored = PoiCollection.model_validate_json(collection.model_dump_json())
    assert restored == collection
