import numpy as np
import pytest
from shapely.geometry import Polygon, box

from amap_pipeline.geo.sfm_heights import (
    HeightParams,
    PointIndex,
    apply_sfm_heights,
    building_heights,
    footprint_height,
)

FOOTPRINT = box(0.0, 0.0, 20.0, 20.0)


def _grid(x0: float, y0: float, x1: float, y1: float, step: float) -> np.ndarray:
    xs, ys = np.meshgrid(np.arange(x0, x1, step), np.arange(y0, y1, step))
    return np.column_stack([xs.ravel(), ys.ravel()])


def _scene(roof_z: float = 12.0, n_inside_step: float = 1.0) -> np.ndarray:
    """Ground ring at z in [0, 0.5], roof points inside at z in [roof-2, roof]."""
    ground_xy = _grid(-10.0, -10.0, 30.0, 30.0, 1.0)
    dist = np.hypot(
        np.clip(ground_xy[:, 0], 0, 20) - ground_xy[:, 0],
        np.clip(ground_xy[:, 1], 0, 20) - ground_xy[:, 1],
    )
    ring = ground_xy[(dist > 3.5) & (dist < 9.5)]
    ground = np.column_stack([ring, np.linspace(0.0, 0.5, len(ring))])
    roof_xy = _grid(2.0, 2.0, 18.0, 18.0, n_inside_step)
    roof = np.column_stack([roof_xy, np.linspace(roof_z - 2.0, roof_z, len(roof_xy))])
    return np.concatenate([ground, roof])


def test_footprint_height_roof_p95_minus_ground_p10() -> None:
    pts = _scene()
    found = footprint_height(PointIndex(pts), FOOTPRINT, None)
    assert found is not None
    roof = pts[pts[:, 2] > 5.0][:, 2]
    ground = pts[pts[:, 2] <= 0.5][:, 2]
    expected = np.quantile(roof, 0.95) - np.quantile(ground, 0.10)
    assert found.height_m == pytest.approx(expected), f"got {found.height_m}"
    assert found.points == len(roof)
    assert found.ground_m == pytest.approx(np.quantile(ground, 0.10))


def test_footprint_height_needs_enough_points_inside() -> None:
    pts = _scene(n_inside_step=4.0)  # 4 x 4 = 16 roof points < 30
    assert footprint_height(PointIndex(pts), FOOTPRINT, None) is None


@pytest.mark.parametrize("roof_z", [2.5, 95.0])
def test_footprint_height_rejects_implausible_heights(roof_z: float) -> None:
    pts = _scene(roof_z=roof_z)
    assert footprint_height(PointIndex(pts), FOOTPRINT, None) is None


def test_footprint_height_ignores_points_inside_neighbour_footprints() -> None:
    pts = _scene()
    neighbour = box(24.0, 0.0, 40.0, 20.0)  # its facade lies in our ground ring
    wall = _grid(24.0, 0.0, 29.0, 20.0, 0.5)
    wall_pts = np.column_stack([wall, np.full(len(wall), -6.0)])  # would pull p10
    cloud = np.concatenate([pts, wall_pts])
    alone = footprint_height(PointIndex(pts), FOOTPRINT, None)
    masked = footprint_height(PointIndex(cloud), FOOTPRINT, neighbour)
    assert alone is not None and masked is not None
    assert masked.ground_m == pytest.approx(alone.ground_m, abs=0.05)


def test_footprint_height_with_normals_uses_only_horizontal_ground() -> None:
    pts = _scene()
    # a hedge in the ground ring: low vertical surface below the ground level
    hedge = np.column_stack([_grid(-6.0, 0.0, -5.0, 20.0, 0.25), np.full(320, -3.0)])
    cloud = np.concatenate([pts, hedge])
    normals = np.tile([0.0, 0.0, 1.0], (len(cloud), 1))
    normals[len(pts) :] = [1.0, 0.0, 0.0]
    clean = footprint_height(PointIndex(pts), FOOTPRINT, None)
    plain = footprint_height(PointIndex(cloud), FOOTPRINT, None)
    with_n = footprint_height(PointIndex(cloud, normals), FOOTPRINT, None)
    assert clean is not None and plain is not None and with_n is not None
    assert plain.ground_m == pytest.approx(-3.0), "facade points pull p10 down"
    assert with_n.ground_m == pytest.approx(clean.ground_m), "normals keep ground"


def test_footprint_height_ignores_points_below_the_ground() -> None:
    pts = _scene()
    reflections = np.column_stack(
        [_grid(4.0, 4.0, 16.0, 16.0, 1.0), np.full(144, -8.0)]
    )
    found = footprint_height(
        PointIndex(np.concatenate([pts, reflections])), FOOTPRINT, None
    )
    clean = footprint_height(PointIndex(pts), FOOTPRINT, None)
    assert found is not None and clean is not None
    assert found.height_m == pytest.approx(clean.height_m)
    assert found.points == clean.points


def test_footprint_height_rejects_ground_far_from_the_model_ground() -> None:
    pts = _scene()
    pts[:, 2] -= 10.0  # a footprint whose "ground" sits 10 m below the cameras
    assert footprint_height(PointIndex(pts), FOOTPRINT, None) is None


def test_footprint_height_ignores_mirror_points_far_below_the_ground() -> None:
    pts = _scene()
    ring = _grid(-9.0, 0.0, -4.0, 20.0, 0.5)
    mirror = np.column_stack([ring, np.full(len(ring), -30.0)])
    found = footprint_height(PointIndex(np.concatenate([pts, mirror])), FOOTPRINT, None)
    clean = footprint_height(PointIndex(pts), FOOTPRINT, None)
    assert found is not None and clean is not None
    assert found.ground_m == pytest.approx(clean.ground_m)


def test_point_index_box_query() -> None:
    pts = np.array([[0.0, 0.0, 1.0], [5.0, 5.0, 2.0], [5.0, 50.0, 3.0]])
    found = PointIndex(pts).box(4.0, 4.0, 6.0, 6.0)
    assert found.tolist() == [[5.0, 5.0, 2.0]]


def test_building_heights_skips_footprints_away_from_the_cloud() -> None:
    far = Polygon([(500, 500), (520, 500), (520, 520), (500, 520)])
    heights = building_heights(
        _scene(), [("way/1", FOOTPRINT), ("way/2", far)], HeightParams()
    )
    assert set(heights) == {"way/1"}
    assert heights["way/1"].as_json()["points"] == heights["way/1"].points


def test_apply_sfm_heights_overrides_only_listed_ids() -> None:
    buildings = [
        {"id": "way/1", "height_m": 9.6, "height_source": "default"},
        {"id": "way/2", "height_m": 12.0, "height_source": "osm_levels"},
    ]
    count = apply_sfm_heights(buildings, {"way/1": {"height_m": 14.234, "points": 80}})
    assert count == 1
    assert buildings[0] == {"id": "way/1", "height_m": 14.23, "height_source": "sfm"}
    assert buildings[1]["height_source"] == "osm_levels"


def test_apply_sfm_heights_never_lowers_an_estimate() -> None:
    buildings = [{"id": "way/1", "height_m": 17.6, "height_source": "default"}]
    count = apply_sfm_heights(buildings, {"way/1": {"height_m": 7.1, "points": 900}})
    assert count == 0
    assert buildings[0] == {"id": "way/1", "height_m": 17.6, "height_source": "default"}
