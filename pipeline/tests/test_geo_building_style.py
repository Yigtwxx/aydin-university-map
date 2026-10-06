from itertools import pairwise

from shapely.geometry import Point, Polygon, box

from amap_pipeline.geo.building_style import (
    classify,
    height_of,
    roof_of,
    style_records,
)
from amap_pipeline.geo.context import Area, Context, Poi
from amap_pipeline.geo.osm import Building
from amap_pipeline.graph.clearance import Obstacles, snap_point, walk_around


def _building(
    outline: Polygon,
    name: str | None = None,
    levels: float | None = None,
    **tags: str,
) -> Building:
    return Building(
        osm_id=f"way/{hash((outline.wkt, name)) & 0xFFFF}",
        name=name,
        levels=levels,
        outline=outline,
        tags={k.replace("_", ":"): v for k, v in tags.items()},
    )


BLOCK = box(0, 0, 20, 12)


def test_classify_campus_name_and_specific_tags() -> None:
    campus = _building(BLOCK, "İstanbul Aydın Üniversitesi A Binası")
    assert classify(campus) == "campus"
    assert classify(_building(BLOCK, building="mosque")) == "worship"
    assert classify(_building(BLOCK, building="hangar")) == "hangar"
    assert classify(_building(BLOCK, building="apartments")) == "apartment"


def test_classify_name_beats_generic_residential_tag() -> None:
    # Mapped as apartments, named as a primary school.
    school = _building(BLOCK, "Mustafapars İlkokulu", building="apartments")
    assert classify(school) == "school"
    assert classify(_building(BLOCK, "Florya Yeni Cami")) == "worship"
    assert classify(_building(BLOCK, "Turkish Technic")) == "hangar"


def test_classify_uses_pois_inside_and_land_use() -> None:
    dealer = Context([], [Poi("shop:car", Point(10, 6))])
    assert classify(_building(BLOCK), dealer) == "showroom"
    estate = Context([Area("landuse:industrial", box(-50, -50, 50, 50))], [])
    assert classify(_building(BLOCK), estate) == "industrial"
    # A shed on a school ground is not a school.
    school = Context([Area("amenity:school", box(-50, -50, 50, 50))], [])
    assert classify(_building(box(0, 0, 8, 10)), school) == "house"


def test_classify_falls_back_on_footprint() -> None:
    assert classify(_building(box(0, 0, 80, 40))) == "industrial"
    assert classify(_building(box(0, 0, 8, 9))) == "house"
    assert classify(_building(BLOCK)) == "apartment"


def test_height_prefers_mapped_levels_and_is_stable() -> None:
    mapped = _building(BLOCK, levels=6)
    height, storeys, source = height_of(mapped, "apartment")
    assert (storeys, source) == (6, "osm_levels")
    assert height == 6 * 3.0 + 0.4
    unmapped = _building(BLOCK)
    first = height_of(unmapped, "apartment")
    assert first == height_of(unmapped, "apartment")
    assert 4 * 3.0 <= first[0] <= 7 * 3.0 + 0.4


def test_roofs_by_style() -> None:
    mosque = _building(box(0, 0, 18, 18), building="mosque")
    dome = roof_of(mosque, "worship", 9.0)
    assert dome["shape"] == "dome"
    assert 7.0 < dome["radius"] < 9.0
    assert tuple(dome["minaret"]) in {
        (0.0, 0.0),
        (18.0, 0.0),
        (18.0, 18.0),
        (0.0, 18.0),
    }
    # Hangars by the old airport have flat metal roofs unless mapped round.
    hangar = roof_of(_building(box(0, 0, 60, 30)), "hangar", 14.0)
    assert hangar["shape"] == "flat", f"Got {hangar}"
    vault = roof_of(_building(box(0, 0, 60, 30), roof_shape="round"), "hangar", 14.0)
    assert vault["shape"] == "barrel" and vault["rise"] > 0, f"Got {vault}"
    office = roof_of(_building(BLOCK), "office", 20.0)
    assert office["shape"] == "flat" and office["unit_kind"] == "hvac"
    assert "parapet" in office


def test_style_records_mark_street_shops() -> None:
    cafe = Context([], [Poi("amenity:cafe", Point(5, 5))])
    [record] = style_records([_building(BLOCK, building="apartments")], cafe)
    assert record["style"] == "apartment" and record["shops"] is True


def test_snap_point_moves_inside_points_just_outside() -> None:
    obstacles = Obstacles.of([BLOCK])
    x, y = snap_point((10.0, 11.0), obstacles)  # a metre inside the north wall
    assert not BLOCK.contains(Point(x, y))
    assert 1.0 <= BLOCK.exterior.distance(Point(x, y)) <= 1.4
    assert snap_point((10.0, 20.0), obstacles) == (10.0, 20.0)


def test_walk_around_avoids_buildings() -> None:
    obstacles = Obstacles.of([BLOCK])
    assert walk_around((-5.0, 6.0), (-5.0, 30.0), obstacles) == [
        (-5.0, 6.0),
        (-5.0, 30.0),
    ]
    path = walk_around((10.0, -5.0), (10.0, 17.0), obstacles)
    assert path is not None and len(path) > 2
    for p, q in pairwise(path):
        assert not obstacles.crosses(p, q)
