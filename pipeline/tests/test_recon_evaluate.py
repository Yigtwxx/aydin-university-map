import math
from pathlib import Path

import numpy as np
import pytest

from amap_pipeline.recon.evaluate import (
    TRIPOD_HEIGHT_M,
    FloatArray,
    PanoPose,
    camera_height,
    edge_lengths_m,
    gravity,
    metric_scale,
    p28_consistency,
    plot_topdown,
    yaw_deg,
)

DOWN = np.array([0.0, 1.0, 0.0])
HEIGHT_UNITS = 0.25  # camera height in model units -> 6.4 m per unit


def _yaw_rotation(degrees: float) -> FloatArray:
    """rig_from_world for a level pano rotated about the world down axis."""
    a = math.radians(degrees)
    world_from_rig = np.array(
        [[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]]
    )
    return world_from_rig.T


def _pose(scene: str, x: float, z: float, yaw: float = 0.0) -> PanoPose:
    center = np.array([x, 0.0, z])
    radii = np.linspace(3, 20, 30) * HEIGHT_UNITS
    angles = np.linspace(0, 2 * math.pi, 30, endpoint=False)
    ground = np.stack(
        [
            x + radii * np.cos(angles),
            np.full(30, HEIGHT_UNITS),
            z + radii * np.sin(angles),
        ],
        axis=1,
    )
    facade = center + np.array([[2.0, -1.0, 0.0], [2.0, -0.5, 0.3], [-2.0, -2.0, 1.0]])
    return PanoPose(scene, center, _yaw_rotation(yaw), np.vstack([ground, facade]))


@pytest.fixture
def poses() -> list[PanoPose]:
    return [_pose("a", 0, 0, 0), _pose("b", 2, 0, 90), _pose("c", 2, 2, 200)]


def test_gravity_level_panos_point_down(poses: list[PanoPose]) -> None:
    down, deviation = gravity(poses)
    assert np.allclose(down, DOWN), f"Got {down}"
    assert deviation < 1e-6, f"Level panos must have ~0 deviation, got {deviation}"


def test_camera_height_ignores_points_above_horizon(poses: list[PanoPose]) -> None:
    height = camera_height(poses[0], DOWN)
    assert height == pytest.approx(HEIGHT_UNITS), f"Got {height}"


def test_camera_height_without_ground_returns_none() -> None:
    pose = PanoPose("x", np.zeros(3), np.eye(3), np.array([[1.0, -1.0, 0.0]]))
    assert camera_height(pose, DOWN) is None


def test_metric_scale_tripod_height_gives_metres_per_unit(
    poses: list[PanoPose],
) -> None:
    scale = metric_scale(poses, DOWN)
    assert scale is not None, "Expected a scale estimate"
    expected = TRIPOD_HEIGHT_M / HEIGHT_UNITS
    assert scale.metres_per_unit == pytest.approx(expected), f"Got {scale}"
    assert scale.cv == pytest.approx(0.0, abs=1e-9), f"Equal heights, got {scale.cv}"


def test_edge_lengths_m_scales_model_distances(poses: list[PanoPose]) -> None:
    lengths = edge_lengths_m(poses, [("a", "b"), ("a", "missing")], 6.4)
    assert lengths == {("a", "b"): pytest.approx(12.8)}, f"Got {lengths}"


def test_yaw_deg_tracks_rotation_about_down(poses: list[PanoPose]) -> None:
    yaws = [yaw_deg(p, DOWN) for p in poses]
    diff = (yaws[1] - yaws[0]) % 360
    assert diff == pytest.approx(90) or diff == pytest.approx(270), f"Got {yaws}"


def test_p28_consistency_detects_compass_like_angle(poses: list[PanoPose]) -> None:
    yaws = {p.scene: yaw_deg(p, DOWN) for p in poses}
    p28 = {s: (30 - y) % 360 for s, y in yaws.items()}
    check = p28_consistency(yaws, p28)
    assert check is not None, "Expected a heading check"
    assert check.sign == -1, f"Got sign {check.sign}"
    assert check.median_abs_residual_deg == pytest.approx(0, abs=1e-6)
    assert check.offset_deg == pytest.approx(30), f"Got offset {check.offset_deg}"


def test_p28_consistency_too_few_scenes_returns_none() -> None:
    assert p28_consistency({"a": 1.0}, {"a": 2.0}) is None


def test_plot_topdown_writes_png(poses: list[PanoPose], tmp_path: Path) -> None:
    path = tmp_path / "plot.png"
    plot_topdown(poses, [("a", "b")], DOWN, 6.4, {"a": "Kampüs"}, path, size=200)
    assert path.stat().st_size > 0, "PNG must not be empty"
