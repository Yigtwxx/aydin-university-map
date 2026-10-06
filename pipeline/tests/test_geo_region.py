from collections.abc import Sequence
from typing import Any

import pytest
from shapely.geometry import Point, Polygon

from amap_contracts import BBox
from amap_pipeline.export.assets import region_json
from amap_pipeline.geo.osm import LocalProjector
from amap_pipeline.geo.region import (
    parse_aeroways,
    parse_land,
    parse_roads,
    parse_sea,
    runway_width_m,
)

M_LAT = 1 / 111_000
M_LNG = 1 / 84_000


@pytest.fixture
def projector() -> LocalProjector:
    return LocalProjector()


@pytest.fixture
def origin_ll(projector: LocalProjector) -> tuple[float, float]:
    lng, lat = projector.to_wgs84(0.0, 0.0)
    return lat, lng


def _geom(
    origin: tuple[float, float], pts: Sequence[tuple[float, float]]
) -> list[dict[str, float]]:
    return [
        {"lat": origin[0] + dy * M_LAT, "lon": origin[1] + dx * M_LNG} for dx, dy in pts
    ]


def _way(
    wid: int,
    tags: dict[str, str],
    origin: tuple[float, float],
    pts: Sequence[tuple[float, float]],
) -> dict[str, Any]:
    return {"type": "way", "id": wid, "tags": tags, "geometry": _geom(origin, pts)}


def _local_bbox(origin: tuple[float, float], half: float) -> BBox:
    return BBox(
        south=origin[0] - half * M_LAT,
        west=origin[1] - half * M_LNG,
        north=origin[0] + half * M_LAT,
        east=origin[1] + half * M_LNG,
    )


def test_parse_sea_coastline_across_bbox_keeps_south_side(
    projector: LocalProjector, origin_ll: tuple[float, float]
) -> None:
    bbox = _local_bbox(origin_ll, 1000.0)
    # West-to-east coastline at y=0 extending past the bbox on both sides.
    payload = {
        "elements": [
            _way(1, {"natural": "coastline"}, origin_ll, [(-1500, 0), (1500, 0)])
        ]
    }
    sea = parse_sea(payload, projector, bbox, tolerance_m=1.0)
    assert len(sea) == 1, f"Expected one sea polygon, got {len(sea)}"
    assert sea[0].contains(Point(0, -500)), "South point must be sea"
    assert not sea[0].intersects(Point(0, 500)), "North point must be land"
    assert sea[0].area == pytest.approx(2000 * 1000, rel=0.02), sea[0].area


def test_parse_sea_two_way_coastline_is_merged(
    projector: LocalProjector, origin_ll: tuple[float, float]
) -> None:
    bbox = _local_bbox(origin_ll, 1000.0)
    payload = {
        "elements": [
            _way(1, {"natural": "coastline"}, origin_ll, [(-1500, 200), (0, 200)]),
            _way(2, {"natural": "coastline"}, origin_ll, [(0, 200), (1500, 200)]),
        ]
    }
    sea = parse_sea(payload, projector, bbox, tolerance_m=1.0)
    assert len(sea) == 1, f"Expected one polygon, got {len(sea)}"
    assert sea[0].contains(Point(0, -900)), "South must be sea"
    assert not sea[0].intersects(Point(0, 900)), "North must be land"


def test_parse_sea_no_coastline_returns_empty(
    projector: LocalProjector, origin_ll: tuple[float, float]
) -> None:
    sea = parse_sea({"elements": []}, projector, _local_bbox(origin_ll, 500.0))
    assert sea == [], f"Expected empty fallback, got {sea}"


def test_parse_sea_coastline_outside_bbox_returns_empty(
    projector: LocalProjector, origin_ll: tuple[float, float]
) -> None:
    payload = {
        "elements": [
            _way(1, {"natural": "coastline"}, origin_ll, [(-900, 5000), (900, 5000)])
        ]
    }
    sea = parse_sea(payload, projector, _local_bbox(origin_ll, 500.0))
    assert sea == [], f"Expected empty fallback, got {sea}"


def test_parse_roads_filters_kinds_and_short_segments(
    projector: LocalProjector, origin_ll: tuple[float, float]
) -> None:
    payload = {
        "elements": [
            _way(
                1, {"highway": "motorway", "name": "O-3"}, origin_ll, [(0, 0), (500, 0)]
            ),
            _way(2, {"highway": "primary_link"}, origin_ll, [(0, 10), (200, 10)]),
            _way(3, {"highway": "residential"}, origin_ll, [(0, 20), (500, 20)]),
            _way(4, {"highway": "trunk"}, origin_ll, [(0, 30), (10, 30)]),
        ]
    }
    roads = parse_roads(payload, projector)
    kinds = sorted(r.kind for r in roads)
    assert kinds == ["motorway", "primary_link"], f"Got {kinds}"
    assert roads[0].name == "O-3", f"Name lost: {roads[0]}"


def test_parse_roads_simplifies_collinear_points(
    projector: LocalProjector, origin_ll: tuple[float, float]
) -> None:
    pts = [(float(x), 0.0) for x in range(0, 501, 25)]
    roads = parse_roads(
        {"elements": [_way(1, {"highway": "trunk"}, origin_ll, pts)]}, projector
    )
    assert len(roads[0].line.coords) == 2, f"Got {len(roads[0].line.coords)} points"


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"width": "60"}, 60.0),
        ({"width": "45 m"}, 45.0),
        ({"width": "30,5"}, 30.5),
        ({"width": "wide"}, 45.0),
        ({"width": "-3"}, 45.0),
        ({}, 45.0),
    ],
)
def test_runway_width_m_parses_or_defaults(
    tags: dict[str, str], expected: float
) -> None:
    assert runway_width_m(tags) == pytest.approx(expected), f"{tags} -> {expected}"


def test_parse_aeroways_reads_runways_and_aerodrome_rings(
    projector: LocalProjector, origin_ll: tuple[float, float]
) -> None:
    ring = [(0, 0), (1000, 0), (1000, 500), (0, 500), (0, 0)]
    payload = {
        "elements": [
            _way(
                1, {"aeroway": "runway", "width": "60"}, origin_ll, [(0, 0), (3000, 0)]
            ),
            _way(2, {"aeroway": "runway"}, origin_ll, [(0, 50), (2000, 50)]),
            _way(3, {"aeroway": "aerodrome", "name": "Way Port"}, origin_ll, ring),
            {
                "type": "relation",
                "id": 4,
                "tags": {"aeroway": "aerodrome", "name": "Rel Port"},
                "members": [
                    {"role": "outer", "geometry": _geom(origin_ll, ring)},
                    {
                        "role": "inner",
                        "geometry": _geom(origin_ll, [*ring[:4], ring[0]]),
                    },
                ],
            },
        ]
    }
    runways, aerodromes = parse_aeroways(payload, projector)
    assert [r.width_m for r in runways] == [60.0, 45.0], f"Got {runways}"
    names = sorted(a.name or "" for a in aerodromes)
    assert names == ["Rel Port", "Way Port"], f"Got {names}"
    assert aerodromes[0].outline.area == pytest.approx(500_000, rel=0.02), "Wrong area"


def test_parse_land_clips_and_simplifies_synthetic_polygon(
    projector: LocalProjector, origin_ll: tuple[float, float]
) -> None:
    lat0, lng0 = origin_ll
    bbox = BBox(
        south=lat0 - 0.01, west=lng0 - 0.01, north=lat0 + 0.01, east=lng0 + 0.01
    )
    # Square far larger than bbox with a noisy (sub-tolerance) top edge.
    ring = [
        [lng0 - 0.1, lat0 - 0.1],
        [lng0 + 0.1, lat0 - 0.1],
        [lng0 + 0.1, lat0 + 0.1],
    ]
    ring += [
        [lng0 + 0.1 - i * 0.004, lat0 + 0.1 + (i % 2) * 1e-5] for i in range(1, 50)
    ]
    ring += [[lng0 - 0.1, lat0 + 0.1], [lng0 - 0.1, lat0 - 0.1]]
    far_away = [
        [lng0 + 1, lat0 + 1],
        [lng0 + 1.1, lat0 + 1],
        [lng0 + 1.1, lat0 + 1.1],
        [lng0 + 1, lat0 + 1],
    ]
    payload = {
        "features": [
            {"geometry": {"type": "Polygon", "coordinates": [ring]}},
            {"geometry": {"type": "Polygon", "coordinates": [far_away]}},
        ]
    }
    land = parse_land(payload, projector, bbox, tolerance_m=120.0)
    assert len(land) == 1, f"Far polygon must be dropped, got {len(land)}"
    minx, _, maxx, _ = land[0].bounds
    assert maxx - minx == pytest.approx(1680, rel=0.05), (
        minx,
        maxx,
    )
    assert len(land[0].exterior.coords) <= 6, (
        f"Got {len(land[0].exterior.coords)} points"
    )
    assert Polygon(land[0]).area > 1e6, "Clipped area unexpectedly small"


def test_region_json_rounds_and_has_schema(
    projector: LocalProjector, origin_ll: tuple[float, float]
) -> None:
    sq = Polygon([(0.123, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    data = region_json([sq], [], [], [], [], [{"kind": "campus"}])
    assert data["crs"] == "local-enu", data["crs"]
    assert data["land"][0]["outer"][0] == [0.1, 0.0], data["land"][0]["outer"][0]
    assert set(data) == {
        "crs",
        "attribution",
        "land",
        "sea_near",
        "roads",
        "runways",
        "aerodromes",
        "campus",
    }, sorted(data)
