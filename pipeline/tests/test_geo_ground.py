from typing import Any

import pytest

from amap_pipeline.export.assets import ground_json
from amap_pipeline.geo.osm import Ground, LocalProjector, parse_ground

# Approximate degrees per metre near the campus origin (lat ~41 N).
M_LAT = 1 / 111_000
M_LNG = 1 / 84_000


def _pt(lat0: float, lng0: float, dx: float, dy: float) -> dict[str, float]:
    return {"lat": lat0 + dy * M_LAT, "lon": lng0 + dx * M_LNG}


@pytest.fixture
def projector() -> LocalProjector:
    return LocalProjector()


@pytest.fixture
def origin_ll(projector: LocalProjector) -> tuple[float, float]:
    lng, lat = projector.to_wgs84(0.0, 0.0)
    return lat, lng


def _way(
    wid: int,
    tags: dict[str, str],
    origin: tuple[float, float],
    pts: list[tuple[float, float]],
) -> dict[str, Any]:
    return {
        "type": "way",
        "id": wid,
        "tags": tags,
        "geometry": [_pt(origin[0], origin[1], dx, dy) for dx, dy in pts],
    }


SQUARE: list[tuple[float, float]] = [(0, 0), (30, 0), (30, 30), (0, 30), (0, 0)]


@pytest.fixture
def ground(projector: LocalProjector, origin_ll: tuple[float, float]) -> Ground:
    payload = {
        "elements": [
            _way(1, {"highway": "footway"}, origin_ll, [(0, 0), (50, 0)]),
            _way(
                2,
                {"highway": "service", "width": "5.5 m"},
                origin_ll,
                [(0, 5), (40, 5)],
            ),
            _way(3, {"highway": "construction"}, origin_ll, [(0, 9), (40, 9)]),
            _way(4, {"highway": "pedestrian", "area": "yes"}, origin_ll, SQUARE),
            _way(
                5,
                {"amenity": "university", "name": "Test Campus"},
                origin_ll,
                [(-50, -50), (100, -50), (100, 100), (-50, 100), (-50, -50)],
            ),
            _way(6, {"highway": "primary"}, origin_ll, [(-5000, 20), (5000, 20)]),
            _way(7, {"highway": "residential"}, origin_ll, [(3000, 0), (3100, 0)]),
        ]
    }
    return parse_ground(payload, projector)


def test_parse_ground_highways_use_default_and_tagged_width(ground: Ground) -> None:
    by_kind = {w.kind: w for w in ground.ways}
    assert by_kind["footway"].width_m == pytest.approx(2.2), by_kind["footway"]
    assert by_kind["service"].width_m == pytest.approx(5.5), by_kind["service"]


def test_parse_ground_skips_construction_highway(ground: Ground) -> None:
    kinds = [w.kind for w in ground.ways]
    assert "construction" not in kinds, f"Got {kinds}"


def test_parse_ground_closed_pedestrian_area_becomes_area(ground: Ground) -> None:
    kinds = [a.kind for a in ground.areas]
    assert "pedestrian" in kinds, f"Got {kinds}"
    assert all(w.kind != "pedestrian" for w in ground.ways), "pedestrian stayed a way"


def test_parse_ground_university_amenity_is_campus_area(ground: Ground) -> None:
    campus = [a for a in ground.areas if a.kind == "campus"]
    assert [a.name for a in campus] == ["Test Campus"], f"Got {campus}"


def test_parse_ground_relation_uses_closed_outer_rings(
    projector: LocalProjector, origin_ll: tuple[float, float]
) -> None:
    ring = [_pt(origin_ll[0], origin_ll[1], dx, dy) for dx, dy in SQUARE]
    payload = {
        "elements": [
            {
                "type": "relation",
                "id": 9,
                "tags": {"amenity": "university", "name": "Rel"},
                "members": [
                    {"role": "outer", "geometry": ring},
                    {"role": "outer", "geometry": ring[:3]},
                    {"role": "inner", "geometry": ring},
                ],
            }
        ]
    }
    result = parse_ground(payload, projector)
    assert [a.kind for a in result.areas] == ["campus"], f"Got {result.areas}"


def test_ground_json_drops_far_features_and_orders_campus_first(
    ground: Ground,
) -> None:
    data = ground_json(ground, radius_m=600.0)
    assert data["areas"][0]["kind"] == "campus", data["areas"]
    assert data["crs"] == "local-enu" and "OpenStreetMap" in data["attribution"]
    far = [w for w in data["ways"] if w["kind"] == "residential"]
    assert far == [], f"Far way kept: {far}"


def test_ground_json_clips_long_road_to_radius_plus_margin(ground: Ground) -> None:
    data = ground_json(ground, radius_m=600.0)
    primary = [w for w in data["ways"] if w["kind"] == "primary"]
    assert len(primary) == 1, f"Got {len(primary)}"
    xs = [p[0] for p in primary[0]["line"]]
    assert max(abs(x) for x in xs) <= 650.0 + 0.1, f"Unclipped extent {max(xs)}"
    assert max(abs(x) for x in xs) > 600.0, "Clipped too tightly"
