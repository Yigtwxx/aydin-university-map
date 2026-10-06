"""Pure-function tests for the earth textures (no network, no real tiles)."""

import math
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon, box

from amap_contracts import CAMPUS_ORIGIN_LAT, CAMPUS_ORIGIN_LNG, BBox
from amap_pipeline.geo.earth import (
    BLACK_MARBLE,
    EOX_S2,
    LAMP_SPECKLE_DEPTH,
    LEVELS,
    NIGHT_GAMMA,
    ROAD_LIGHTS,
    TERRARIUM,
    TILE_PX,
    EarthLevel,
    Grid,
    Mosaic,
    antialias_sigma,
    built_up,
    compose_night,
    fill_rings,
    finish_heights,
    lamp_speckle,
    lnglat_bbox,
    lnglat_to_px,
    manifest,
    mercator_m_per_px,
    mosaic_index,
    parse_lit_roads,
    patiently,
    px_to_lnglat,
    rasterize_polygons,
    redistribute,
    resample,
    shore_distance_m,
    soft_knee,
    split_bbox,
    terrarium_decode,
    terrarium_encode,
    tile_cache_path,
    tile_span,
    tone_map,
    water_texture,
    wide_blur,
)
from amap_pipeline.geo.osm import LocalProjector
from amap_pipeline.geo.region import (
    classify_faces,
    coastline_faces,
    parse_water_bodies,
)

M_LAT = 1 / 111_000
M_LNG = 1 / 84_000


@pytest.fixture(scope="module")
def projector() -> LocalProjector:
    return LocalProjector()


def _level(
    size_m: float = 8000.0, centre: tuple[float, float] = (0.0, 0.0)
) -> EarthLevel:
    return EarthLevel(
        id="T",
        centre=centre,
        size_m=size_m,
        day_px=8,
        height_px=4,
        water_px=8,
        day_zoom=15,
        terrain_zoom=14,
        night_zoom=8,
        min_water_m2=0.0,
    )


# --- Web Mercator tile math ----------------------------------------------------------


def test_lnglat_to_px_world_corners_and_centre() -> None:
    px, py = lnglat_to_px(0.0, 0.0, 0)
    assert (float(px), float(py)) == pytest.approx((128.0, 128.0))
    px, py = lnglat_to_px(-180.0, 85.0511287798, 2)
    assert (float(px), float(py)) == pytest.approx((0.0, 0.0), abs=1e-6)
    px, py = lnglat_to_px(180.0, -85.0511287798, 2)
    assert (float(px), float(py)) == pytest.approx((1024.0, 1024.0), abs=1e-6)


def test_px_to_lnglat_round_trips_at_high_zoom() -> None:
    lng = np.array([28.7971, 29.12, -73.98])
    lat = np.array([40.9915, 41.23, 40.75])
    back_lng, back_lat = px_to_lnglat(*lnglat_to_px(lng, lat, 15), 15)
    np.testing.assert_allclose(back_lng, lng, atol=1e-10)
    np.testing.assert_allclose(back_lat, lat, atol=1e-10)


def test_golden_horn_falls_in_the_known_z11_tile() -> None:
    # Tile 11/1188/767 shows the Golden Horn and the Bosphorus mouth.
    px, py = lnglat_to_px(28.97, 41.03, 11)
    tile = (math.floor(float(px) / TILE_PX), math.floor(float(py) / TILE_PX))
    assert tile == (1188, 767), tile


def test_mercator_m_per_px_matches_the_standard_table() -> None:
    assert mercator_m_per_px(0.0, 0) == pytest.approx(156_543.034, rel=1e-6)
    assert mercator_m_per_px(60.0, 1) == pytest.approx(156_543.034 / 4, rel=1e-6)


def test_tile_span_covers_bbox_with_margin_and_clamps() -> None:
    bbox = BBox(south=40.9, west=28.7, north=41.1, east=29.0)
    span = tile_span(bbox, 12, margin_px=0.0)
    for lng, lat in ((28.7, 41.1), (29.0, 40.9), (28.85, 41.0)):
        px, py = lnglat_to_px(lng, lat, 12)
        assert span.x0 * TILE_PX <= px < (span.x1 + 1) * TILE_PX
        assert span.y0 * TILE_PX <= py < (span.y1 + 1) * TILE_PX
    rows, cols = span.shape_px
    assert rows == (span.y1 - span.y0 + 1) * TILE_PX
    assert cols == (span.x1 - span.x0 + 1) * TILE_PX
    assert len(span.tiles()) == (span.x1 - span.x0 + 1) * (span.y1 - span.y0 + 1)
    world = tile_span(BBox(south=-85.0, west=-180.0, north=85.0, east=180.0), 1, 50)
    assert (world.x0, world.y0, world.x1, world.y1) == (0, 0, 1, 1)


def test_tile_urls_and_cache_layout(tmp_path: Path) -> None:
    assert EOX_S2.tile_url(11, 1188, 767).endswith("/g/11/767/1188.jpg")
    assert BLACK_MARBLE.tile_url(8, 148, 95).endswith("_Level8/8/95/148.png")
    assert TERRARIUM.tile_url(10, 594, 383).endswith("/terrarium/10/594/383.png")
    path = tile_cache_path(tmp_path, TERRARIUM, 10, 594, 383)
    assert path == tmp_path / "terrarium" / "10" / "594" / "383.png"


# --- Terrarium codec -----------------------------------------------------------------


def test_terrarium_decode_known_pixels() -> None:
    rgb = np.array([[[128, 0, 0], [127, 255, 128], [129, 44, 64]]], dtype=np.uint8)
    np.testing.assert_allclose(terrarium_decode(rgb)[0], [0.0, -0.5, 300.25])


def test_terrarium_encode_is_exact_for_zero_and_round_trips() -> None:
    assert terrarium_encode(0.0).tolist() == [128, 0, 0]
    assert terrarium_encode(-0.5).tolist() == [127, 255, 128]
    heights = np.linspace(-120.0, 2900.0, 1001)
    back = terrarium_decode(terrarium_encode(heights))
    np.testing.assert_allclose(back, heights, atol=1 / 512 + 1e-6)


# --- grids ---------------------------------------------------------------------------


def test_grid_row_zero_is_north_and_column_zero_is_west() -> None:
    grid = Grid.of(_level(size_m=80.0, centre=(100.0, -40.0)), 8)
    xs, ys = grid.centres()
    assert grid.step_m == 10.0
    assert grid.bounds == (60.0, -80.0, 140.0, 0.0)
    assert xs[0] == 65.0 and xs[-1] == 135.0, xs
    assert ys[0] == -5.0 and ys[-1] == -75.0, ys
    col, row = grid.to_pixel(xs, ys)
    np.testing.assert_allclose(col, np.arange(8) + 0.5)
    np.testing.assert_allclose(row, np.arange(8) + 0.5)
    padded = grid.padded(2)
    assert padded.px == 12
    assert padded.bounds == (40.0, -100.0, 160.0, 20.0)


def test_grid_lnglat_is_oriented_and_centred_on_the_origin(
    projector: LocalProjector,
) -> None:
    grid = Grid.of(_level(size_m=3000.0), 3)
    lng, lat = grid.lnglat(projector)
    assert lng.shape == (3, 3)
    assert float(lng[1, 1]) == pytest.approx(CAMPUS_ORIGIN_LNG, abs=1e-7)
    assert float(lat[1, 1]) == pytest.approx(CAMPUS_ORIGIN_LAT, abs=1e-7)
    assert (lat[0] > lat[2]).all(), "row 0 must be north"
    assert (lng[:, 0] < lng[:, 2]).all(), "column 0 must be west"
    # 1 km between pixel centres.
    assert float(lat[0, 1] - lat[1, 1]) == pytest.approx(1000 * M_LAT, rel=0.02)


def test_grid_lnglat_rows_slice_matches_the_full_grid(
    projector: LocalProjector,
) -> None:
    grid = Grid.of(_level(), 6)
    lng, lat = grid.lnglat(projector)
    part_lng, part_lat = grid.lnglat(projector, slice(2, 4))
    np.testing.assert_allclose(part_lng, lng[2:4])
    np.testing.assert_allclose(part_lat, lat[2:4])


def test_lnglat_bbox_contains_every_corner(projector: LocalProjector) -> None:
    bounds = (-5000.0, -3000.0, 7000.0, 9000.0)
    bbox = lnglat_bbox(bounds, projector)
    for x in (bounds[0], bounds[2]):
        for y in (bounds[1], bounds[3]):
            lng, lat = projector.to_wgs84(x, y)
            assert bbox.west - 1e-9 <= lng <= bbox.east + 1e-9
            assert bbox.south - 1e-9 <= lat <= bbox.north + 1e-9


# --- resampling ----------------------------------------------------------------------


def test_mosaic_index_uses_pixel_centres() -> None:
    mosaic = Mosaic(np.zeros((4, 4, 1), np.float32), 10, (1000.0, 2000.0))
    lng, lat = px_to_lnglat(1000.0 + 10.5, 2000.0 + 5.5, 10)
    row, col = mosaic_index(mosaic, lng, lat)
    assert (float(row), float(col)) == pytest.approx((5.0, 10.0), abs=1e-6)


def test_resample_reproduces_a_linear_mosaic_exactly(
    projector: LocalProjector,
) -> None:
    zoom = 16
    grid = Grid.of(_level(size_m=600.0), 5)
    lng, lat = grid.lnglat(projector)
    px, py = lnglat_to_px(lng, lat, zoom)
    x0, y0 = math.floor(px.min()) - 4, math.floor(py.min()) - 4
    rows, cols = int(py.max()) - y0 + 6, int(px.max()) - x0 + 6
    # Channel 0 holds each pixel's global x centre, channel 1 its y centre.
    cc, rr = np.meshgrid(np.arange(cols), np.arange(rows))
    data = np.stack([x0 + cc + 0.5, y0 + rr + 0.5], axis=-1).astype(np.float32)
    mosaic = Mosaic(data, zoom, (float(x0), float(y0)))
    out = resample(mosaic, grid, projector, order=1, block_rows=2)
    np.testing.assert_allclose(out[..., 0], px, atol=2e-2)
    np.testing.assert_allclose(out[..., 1], py, atol=2e-2)


def test_antialias_sigma_only_when_downsampling() -> None:
    assert antialias_sigma(10.0, 5.0) == 0.0
    assert antialias_sigma(10.0, 10.0) == 0.0
    assert antialias_sigma(10.0, 30.0) == pytest.approx(0.5 * math.sqrt(8))


# --- rasterisation and water ---------------------------------------------------------


def test_rasterize_half_plane_is_pixel_exact() -> None:
    grid = Grid(west=0.0, north=8.0, step_m=1.0, px=8)
    cover = rasterize_polygons(box(-5.0, -5.0, 4.0, 13.0), grid, supersample=4)
    np.testing.assert_allclose(cover[:, :4], 1.0)
    np.testing.assert_allclose(cover[:, 4:], 0.0)
    half = rasterize_polygons(box(-5.0, -5.0, 4.5, 13.0), grid, supersample=4)
    np.testing.assert_allclose(half[:, 4], 0.5)


def test_rasterize_cuts_holes_and_paints_nested_parts() -> None:
    grid = Grid(west=0.0, north=10.0, step_m=1.0, px=10)
    sea = Polygon(
        [(-1, -1), (11, -1), (11, 11), (-1, 11)], [[(2, 2), (8, 2), (8, 8), (2, 8)]]
    )
    lake = box(4.0, 4.0, 6.0, 6.0)  # on the island, drawn after the hole
    cover = rasterize_polygons(sea.union(lake), grid, supersample=2)
    assert cover[0, 0] == 1.0, "sea"
    assert cover[3, 3] == 0.0, "island"
    assert cover[5, 5] == 1.0, "lake on the island"


def test_fill_rings_matches_triangle_area_and_clips_to_the_canvas() -> None:
    triangle = np.array([[0.0, 0.0], [64.0, 0.0], [0.0, 64.0], [0.0, 0.0]])
    filled = fill_rings([triangle], 64)
    assert filled.sum() == pytest.approx(64 * 64 / 2, rel=0.02), filled.sum()
    # A band running past both side edges fills whole rows.
    band = np.array(
        [[-10.0, 2.0], [80.0, 2.0], [80.0, 4.0], [-10.0, 4.0], [-10.0, 2.0]]
    )
    rows = fill_rings([band], 8)
    assert rows[2:4].all() and not rows[:2].any() and not rows[4:].any(), rows
    assert not fill_rings([], 4).any()


def test_shore_distance_grows_away_from_land_and_clamps() -> None:
    water = np.zeros((3, 8), dtype=bool)
    water[:, 3:] = True
    dist = shore_distance_m(water, step_m=100.0, max_m=300.0)
    np.testing.assert_allclose(dist[1], [0, 0, 0, 50, 150, 250, 300, 300])
    assert shore_distance_m(np.zeros((2, 2), bool), 10.0).max() == 0.0
    assert shore_distance_m(np.ones((2, 2), bool), 10.0, 99.0).min() == 99.0


def test_water_texture_channels() -> None:
    cover = np.array([[0.0, 0.5, 1.0]], np.float32)
    dist = np.array([[0.0, 0.0, 750.0]], np.float32)
    tex = water_texture(cover, dist, max_m=1500.0)
    assert tex.shape == (1, 3, 3)
    assert tex[0, :, 0].tolist() == [0, 128, 255]
    assert tex[0, :, 1].tolist() == [0, 0, 128]
    assert tex[..., 2].max() == 0


def test_finish_heights_zeroes_the_sea_and_lifts_land() -> None:
    heights = np.array([[-12.0, 0.1, 35.0, 12.34]], np.float32)
    sea = np.array([[True, False, False, False]])
    out = finish_heights(heights, sea)
    assert out.tolist() == [[0.0, 0.5, 35.0, 12.375]], out


def test_finish_heights_keeps_lakes_flat_at_their_own_level() -> None:
    heights = np.array([[60.0, 61.0, 90.0, 0.0], [59.0, 62.0, 95.0, 1.0]], np.float32)
    sea = np.zeros((2, 4), bool)
    sea[:, 3] = True
    lakes = np.zeros((2, 4), bool)
    lakes[:, :2] = True  # a reservoir in a valley at ~60 m
    lakes[:, 3] = True  # a lake polygon overlapping the sea stays sea
    out = finish_heights(heights, sea, lakes, step_m=0.0)
    np.testing.assert_allclose(out[:, :2], 60.5)
    np.testing.assert_allclose(out[:, 2], [90.0, 95.0])
    assert (out[:, 3] == 0.0).all(), out


def test_parse_water_bodies_assembles_relations_with_holes(
    projector: LocalProjector,
) -> None:
    def ring(pts: list[tuple[float, float]]) -> list[dict[str, float]]:
        return [
            {"lat": CAMPUS_ORIGIN_LAT + y * M_LAT, "lon": CAMPUS_ORIGIN_LNG + x * M_LNG}
            for x, y in pts
        ]

    outer_a = ring([(0, 0), (1000, 0), (1000, 1000)])
    outer_b = ring([(1000, 1000), (0, 1000), (0, 0)])  # one ring, two ways
    inner = ring([(400, 400), (600, 400), (600, 600), (400, 600), (400, 400)])
    pond = ring([(2000, 0), (2100, 0), (2100, 100), (2000, 100), (2000, 0)])
    payload = {
        "elements": [
            {
                "type": "relation",
                "id": 1,
                "tags": {"natural": "water"},
                "members": [
                    {"type": "way", "role": "outer", "geometry": outer_a},
                    {"type": "way", "role": "outer", "geometry": outer_b},
                    {"type": "way", "role": "inner", "geometry": inner},
                ],
            },
            {"type": "way", "id": 2, "tags": {"natural": "water"}, "geometry": pond},
        ]
    }
    bodies = sorted(parse_water_bodies(payload, projector), key=lambda p: -p.area)
    assert len(bodies) == 2, bodies
    assert bodies[0].area == pytest.approx(1_000_000 - 40_000, rel=0.03)
    assert len(bodies[0].interiors) == 1
    assert bodies[1].area == pytest.approx(10_000, rel=0.03)


# --- coastline orientation ------------------------------------------------------------


def test_coastline_faces_follow_land_on_the_left() -> None:
    frame = box(-1000.0, -1000.0, 1000.0, 1000.0)
    # Heading east with land on the left: north is land, south is sea.
    east = LineString([(-1500, 0), (1500, 0)])
    land, water = classify_faces(coastline_faces([east], frame))
    assert len(land) == 1 and len(water) == 1
    assert land[0].centroid.y > 0 > water[0].centroid.y
    # The same line heading west flips the sides.
    land, water = classify_faces(
        coastline_faces([LineString(east.coords[::-1])], frame)
    )
    assert land[0].centroid.y < 0 < water[0].centroid.y


def test_coastline_island_ring_is_land_inside_the_sea() -> None:
    frame = box(-1000.0, -1000.0, 1000.0, 1000.0)
    shore = LineString([(1500, -500), (-1500, -500)])  # heading west: land south
    island = LineString([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)])  # CCW
    land, water = classify_faces(coastline_faces([shore, island], frame))
    assert len(water) == 1, water
    assert len(water[0].interiors) == 1, "the island is a hole in the sea"
    assert any(p.contains(box(50, 50, 150, 150)) for p in land), "island is land"
    assert water[0].area == pytest.approx(2000 * 1500 - 200 * 200, rel=1e-6)


def test_frame_without_coastline_uses_the_fallback() -> None:
    frame = box(0.0, 0.0, 100.0, 100.0)
    faces = coastline_faces([], frame)
    assert len(faces) == 1 and faces[0].vote == 0
    land, water = classify_faces(faces, fallback_land=box(-10.0, -10.0, 20.0, 20.0))
    assert not land and len(water) == 1


# --- night ---------------------------------------------------------------------------


def test_parse_lit_roads_flags_bridges(projector: LocalProjector) -> None:
    def geom(pts: list[tuple[float, float]]) -> list[dict[str, float]]:
        return [
            {"lat": CAMPUS_ORIGIN_LAT + y * M_LAT, "lon": CAMPUS_ORIGIN_LNG + x * M_LNG}
            for x, y in pts
        ]

    payload = {
        "elements": [
            {
                "type": "way",
                "tags": {"highway": "motorway", "bridge": "yes"},
                "geometry": geom([(0, 0), (100, 0)]),
            },
            {
                "type": "way",
                "tags": {"highway": "primary"},
                "geometry": geom([(0, 0), (0, 100), (50, 150)]),
            },
            {
                "type": "way",
                "tags": {"highway": "footway"},
                "geometry": geom([(0, 0), (5, 5)]),
            },
        ]
    }
    roads = parse_lit_roads(payload, projector, ("motorway", "primary"))
    assert [(r.kind, r.bridge) for r in roads] == [
        ("motorway", True),
        ("primary", False),
    ]
    assert roads[0].line.length == pytest.approx(100.0, rel=0.02)
    assert len(roads[1].line.coords) == 3


def test_split_bbox_tiles_the_box_exactly() -> None:
    bbox = BBox(south=40.0, west=28.0, north=41.0, east=30.0)
    parts = split_bbox(bbox, 2)
    assert len(parts) == 4
    assert parts[0] == BBox(south=40.0, west=28.0, north=40.5, east=29.0)
    assert parts[-1] == BBox(south=40.5, west=29.0, north=41.0, east=30.0)
    assert split_bbox(bbox, 1) == [bbox]


def test_patiently_retries_until_success_then_gives_up() -> None:
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("busy")
        return "ok"

    assert patiently(flaky, rounds=3, wait_s=0.0) == "ok"
    assert len(calls) == 3, calls

    def down() -> str:
        raise RuntimeError("down")

    with pytest.raises(RuntimeError, match="down"):
        patiently(down, rounds=2, wait_s=0.0)


def _decode(srgb: np.ndarray) -> np.ndarray:
    return (srgb.astype(np.float64) / 255.0) ** NIGHT_GAMMA


def test_compose_night_plain_is_warm_light_on_land_only() -> None:
    bm = np.array([[[0.9, 0.9, 0.9], [0.9, 0.9, 0.9], [0.0, 0.0, 0.0]]], np.float32)
    water = np.array([[1.0, 0.0, 0.0]], np.float32)
    out = compose_night(bm, water)
    assert out[0, 0].max() == 0, f"water must be black, got {out[0, 0]}"
    assert out[0, 2].max() == 0, f"unlit land must stay dark, got {out[0, 2]}"
    r, g, b = out[0, 1].tolist()
    assert r > g > b and r > 100, f"lit land must glow warm, got {(r, g, b)}"


def test_compose_night_lights_roads_and_bridges_but_not_dark_land() -> None:
    bm = np.full((8, 8, 3), 0.9, np.float32)
    bm[:, 6:] = 0.0  # unlit countryside on the east
    water = np.zeros((8, 8), np.float32)
    water[:, :2] = 1.0  # sea on the west
    on_land = np.zeros((8, 8, 3), np.float32)
    on_land[4, :] = 1.0  # an east-west road ...
    bridges = np.zeros((8, 8, 3), np.float32)
    bridges[4, :2] = 1.0  # ... crossing the sea on a bridge
    built = np.ones((8, 8), np.float32)
    out = compose_night(bm, water, (on_land, bridges), built, spread_px=2.0)
    assert out[4, 0].max() > 60, f"bridge light over water, got {out[4, 0]}"
    assert out[1, 0].max() == 0, f"open water is black, got {out[1, 0]}"
    assert out[4, 4].sum() > out[1, 4].sum(), "the road outshines the blocks"
    assert out[4, 7].max() <= 2, f"unlit land stays dark, got {out[4, 7]}"


def test_redistribute_conserves_the_mean_and_favours_roads() -> None:
    emit = np.full((32, 32), 0.25, np.float32)
    light = np.repeat(emit[..., None], 3, axis=2)  # unit-luma white hue
    fabric = np.full((32, 32), 0.05, np.float32)
    fabric[:16] = 0.15  # denser blocks in the north
    road = np.zeros((32, 32, 3), np.float32)
    road[:, 20] = 4.0  # one north-south road
    total = redistribute(light, emit, fabric, road, spread_px=1000.0)
    luma = total @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    assert float(luma.mean()) == pytest.approx(0.25, rel=0.03), luma.mean()
    assert luma[5, 20] > luma[5, 5] > luma[25, 5], "road > dense > sparse"


def test_tone_map_keeps_hue_and_leaves_darks_alone() -> None:
    dark = np.array([[0.2, 0.1, 0.05]], np.float32)
    np.testing.assert_allclose(tone_map(dark), dark, rtol=1e-6)
    hot = tone_map(np.array([[2.0, 1.0, 0.5]], np.float32))[0]
    assert hot[0] == 1.0 and 0 < hot[1] < 1.0, hot
    assert hot[2] / hot[1] == pytest.approx(0.5, rel=1e-5), "hue kept"
    knee = soft_knee(np.array([0.3, 0.6, 1.0, 2.0, 50.0]))
    assert knee[0] == pytest.approx(0.3) and knee[1] == pytest.approx(0.6)
    assert (np.diff(knee) >= 0).all() and knee[3] < 1.0 and knee[-1] <= 1.0, knee


def test_built_up_separates_roofs_from_vegetation() -> None:
    roof = [140, 110, 90]  # reddish roof
    forest = [50, 64, 40]  # dark green canopy
    shadow = [20, 20, 22]
    built = built_up(np.array([[roof, forest, shadow]], np.uint8))[0]
    assert built[0] > 0.6, built
    assert built[1] < 0.05 and built[2] == 0.0, built


def test_wide_blur_keeps_constants_and_matches_a_direct_gaussian() -> None:
    flat = np.full((64, 64), 0.3, np.float32)
    np.testing.assert_allclose(wide_blur(flat, 40.0), 0.3, rtol=1e-5)
    ramp = np.tile(np.linspace(0.0, 1.0, 64, dtype=np.float32), (64, 1))
    fast = wide_blur(ramp, 12.0)  # block-averaged path
    assert fast.shape == ramp.shape
    np.testing.assert_allclose(fast[:, 16:48], ramp[:, 16:48], atol=0.03)


def test_lamp_speckle_is_deterministic_and_bounded() -> None:
    fine = Grid(west=0.0, north=0.0, step_m=2.0, px=32)
    a, b = lamp_speckle(fine), lamp_speckle(fine)
    np.testing.assert_array_equal(a, b)
    assert a.min() >= 1 - LAMP_SPECKLE_DEPTH - 1e-6 and a.max() <= 1.0 + 1e-6
    assert a.std() > 0.05, "visible beads at 2 m/px"
    coarse = Grid(west=0.0, north=0.0, step_m=50.0, px=8)
    assert (lamp_speckle(coarse) == 1.0).all()


# --- levels and manifest --------------------------------------------------------------


def test_levels_are_nested_and_within_source_zooms() -> None:
    for outer, inner in pairwise(LEVELS):
        ow, os_, oe, on = outer.bounds
        iw, is_, ie, in_ = inner.bounds
        assert ow <= iw and os_ <= is_ and ie <= oe and in_ <= on, (outer, inner)
    for level in LEVELS:
        assert level.day_zoom <= EOX_S2.max_zoom
        assert level.terrain_zoom <= TERRARIUM.max_zoom
        assert level.night_zoom <= BLACK_MARBLE.max_zoom
        assert set(level.road_kinds) <= set(ROAD_LIGHTS), level.road_kinds


def test_region_level_covers_bosphorus_and_marmara(projector: LocalProjector) -> None:
    west, south, east, north = LEVELS[0].bounds
    for lng, lat in ((29.12, 41.23), (28.9, 40.6), (29.15, 41.25)):
        x, y = projector.to_local(lng, lat)
        assert west < x < east and south < y < north, (lng, lat, x, y)
    # The campus sits at the centre of the finest level.
    assert LEVELS[-1].centre == (0.0, 0.0)


def test_manifest_shape() -> None:
    data = manifest(LEVELS, (0.0, 512.345), ["A", "B"])
    assert data["version"] == 1
    assert data["crs"] == "local-utm35n"
    assert data["origin"] == {"lat": CAMPUS_ORIGIN_LAT, "lng": CAMPUS_ORIGIN_LNG}
    assert data["height_range_m"] == [0.0, 512.35]
    assert data["attribution"] == ["A", "B"]
    assert [lv["id"] for lv in data["levels"]] == ["L0", "L1", "L2"]
    first = data["levels"][0]
    assert set(first) == {"id", "centre", "size_m", "day", "night", "height", "water"}
    assert first["day"] == {"file": "day_L0.webp", "px": LEVELS[0].day_px}
    assert first["night"]["file"] == "night_L0.webp"
    assert first["height"] == {
        "file": "height_L0.png",
        "px": LEVELS[0].height_px,
        "encoding": "terrarium",
    }
    assert first["water"] == {
        "file": "water_L0.png",
        "px": LEVELS[0].water_px,
        "shore_max_m": 1500.0,
    }
    for level in data["levels"]:
        for layer in ("day", "night", "height", "water"):
            assert "/" not in level[layer]["file"], "files are relative names"
