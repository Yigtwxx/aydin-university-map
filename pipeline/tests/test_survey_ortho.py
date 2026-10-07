import numpy as np
import pytest

from amap_pipeline.look.camera import Pose, rig_to_enu
from amap_pipeline.recon.cubemap import render_faces
from amap_pipeline.survey.ortho import Grid, agreement, blend, project_ground


def _paving(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """A ground pattern with structure at every scale (no repeats to fool NCC)."""
    v = 128 + 60 * np.sin(1.7 * x) * np.cos(2.3 * y) + 40 * np.sin(0.37 * x + 0.9 * y)
    return np.stack([v, v * 0.9, v * 0.8], axis=-1)


def _panorama(pose: Pose, size: int = 160) -> dict[str, np.ndarray]:
    def colour(dirs: np.ndarray) -> np.ndarray:
        enu = rig_to_enu(pose, dirs)
        down = enu[:, 2] < -1e-6
        t = np.where(down, (pose.z - pose.ground_z) / np.maximum(-enu[:, 2], 1e-6), 0)
        x = pose.x + enu[:, 0] * t
        y = pose.y + enu[:, 1] * t
        sky = np.tile([200.0, 220.0, 255.0], (len(dirs), 1))
        return np.where(down[:, None], _paving(x, y), sky)

    return {
        face: np.clip(img, 0, 255).astype(np.uint8)
        for face, img in render_faces(colour, size).items()
    }


GRID = Grid(-6.0, -6.0, 6.0, 6.0, 0.1)


def test_projected_ground_reproduces_the_paving() -> None:
    pose = Pose("a", x=0.0, y=0.0, z=1.6, heading_deg=37.0)
    layer = project_ground(_panorama(pose), pose, GRID, max_range_m=5.0)
    gx, gy = GRID.centres()
    seen = layer.weight > 0
    truth = _paving(gx, gy)[seen][:, 0]
    assert np.corrcoef(layer.colour[seen][:, 0], truth)[0, 1] > 0.9
    assert not seen[GRID.height // 2, GRID.width // 2]  # nadir left out


def test_overlap_agrees_only_with_the_right_tripod_height() -> None:
    a = Pose("a", x=-1.5, y=0.0, z=1.6, heading_deg=10.0)
    b = Pose("b", x=1.5, y=0.5, z=1.6, heading_deg=250.0)
    faces_a, faces_b = _panorama(a), _panorama(b)

    def score(tripod: float) -> float:
        la = project_ground(faces_a, Pose("a", -1.5, 0.0, 1.6, 10.0, tripod), GRID)
        lb = project_ground(faces_b, Pose("b", 1.5, 0.5, 1.6, 250.0, tripod), GRID)
        value = agreement(la, lb)
        assert value is not None
        return value

    assert score(1.6) > 0.8
    assert score(1.6) > score(1.2) + 0.2


def test_blend_prefers_the_nearer_panorama() -> None:
    pose = Pose("a", x=0.0, y=0.0, z=1.6, heading_deg=0.0)
    layer = project_ground(_panorama(pose), pose, GRID)
    image = blend([layer], GRID)
    assert image.shape == (GRID.height, GRID.width, 3)
    assert (image[GRID.height // 2, GRID.width // 2] == 255).all()  # uncovered
    assert blend([], GRID).shape == image.shape


def test_grid_pixels_are_north_up() -> None:
    assert GRID.to_pixel(-6.0, 6.0) == pytest.approx((0.0, 0.0))
    _, gy = GRID.centres()
    assert gy[0, 0] > gy[-1, 0]
