from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from amap_pipeline.commands.look import tour_path
from amap_pipeline.look.camera import (
    Pose,
    ath_to_bearing,
    bearing_to_ath,
    enu_to_angles,
    enu_to_rig,
    ground_point,
    rig_angles,
    rig_rays,
    rig_to_enu,
)
from amap_pipeline.look.context import building_code, parse_buildings
from amap_pipeline.look.edges import snap_edge
from amap_pipeline.look.render import FaceCache, Strip, View, render_strip, render_view
from amap_pipeline.look.sample import sample_colour, srgb_to_oklab
from amap_pipeline.recon.cubemap import FACES, render_faces

SIZE = 64


def _faces(colour) -> dict[str, np.ndarray]:
    return {
        face: np.clip(img, 0, 255).astype(np.uint8)
        for face, img in render_faces(colour, SIZE).items()
    }


def _direction_faces() -> dict[str, np.ndarray]:
    """Each pixel encodes its own rig direction: rgb = 127.5 * (dir + 1)."""
    return _faces(lambda d: 127.5 * (d + 1.0))


def _decode(rgb: np.ndarray) -> np.ndarray:
    d = rgb.astype(np.float64) / 127.5 - 1.0
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


@pytest.mark.parametrize(
    ("ath", "atv", "expected"),
    [
        (0.0, 0.0, (0.0, 0.0, 1.0)),
        (90.0, 0.0, (1.0, 0.0, 0.0)),  # krpano right = rig +x = face r
        (180.0, 0.0, (0.0, 0.0, -1.0)),
        (0.0, 90.0, (0.0, 1.0, 0.0)),  # atv +90 = straight down = rig +y
    ],
)
def test_rig_rays_follow_krpano_angles(
    ath: float, atv: float, expected: tuple[float, float, float]
) -> None:
    ray = rig_rays(np.array([ath]), np.array([atv]))[0]
    assert ray == pytest.approx(expected, abs=1e-12), f"Got {ray}"


def test_rig_angles_invert_rig_rays() -> None:
    ath = np.array([0.0, 37.3, 181.0, 359.0])
    atv = np.array([0.0, -20.0, 45.0, 10.0])
    back_ath, back_atv = rig_angles(rig_rays(ath, atv))
    assert back_ath == pytest.approx(ath)
    assert back_atv == pytest.approx(atv)


def test_enu_angles_add_heading() -> None:
    pose = Pose("s", x=10.0, y=20.0, z=1.6, heading_deg=30.0)
    # A point due east and level with the camera: bearing 90 -> ath 60.
    ath, atv, dist = enu_to_angles(pose, np.array([[15.0, 20.0, 1.6]]))
    assert ath[0] == pytest.approx(60.0)
    assert atv[0] == pytest.approx(0.0)
    assert dist[0] == pytest.approx(5.0)
    assert ath_to_bearing(pose, 60.0) == pytest.approx(90.0)
    assert bearing_to_ath(pose, 90.0) == pytest.approx(60.0)


def test_rig_to_enu_inverts_enu_to_rig() -> None:
    pose = Pose("s", x=0.0, y=0.0, z=0.0, heading_deg=217.0)
    points = np.array([[3.0, -4.0, 1.0], [-2.0, 5.0, -0.5]])
    assert rig_to_enu(pose, enu_to_rig(pose, points)) == pytest.approx(points)


def test_ground_point_uses_camera_height() -> None:
    pose = Pose("s", x=0.0, y=0.0, z=1.6, heading_deg=90.0, tripod_m=1.6)
    # 45° down, straight ahead (east): the floor 1.6 m away.
    point = ground_point(pose, 0.0, 45.0)
    assert point is not None
    assert point == pytest.approx((1.6, 0.0))
    assert ground_point(pose, 0.0, -5.0) is None


def test_view_centre_pixel_looks_where_asked() -> None:
    faces = _direction_faces()
    view = View(ath_deg=120.0, atv_deg=-10.0, hfov_deg=60.0, width=41, height=31)
    image = render_view(faces, view)
    seen = _decode(image[15, 20])
    expected = rig_rays(np.array([120.0]), np.array([-10.0]))[0]
    assert float(seen @ expected) > 0.999, f"Got {seen}, expected {expected}"


def test_view_to_pixels_inverts_pixel_rays() -> None:
    view = View(ath_deg=300.0, atv_deg=5.0, hfov_deg=80.0, width=64, height=40)
    rays = view.pixel_rays()
    uv, front = view.to_pixels(rays)
    assert front.all()
    expected_u = (np.arange(64) + 0.5)[None, :].repeat(40, axis=0).ravel()
    assert uv[:, 0] == pytest.approx(expected_u)


def test_strip_columns_are_constant_ath() -> None:
    faces = _direction_faces()
    strip = Strip(
        ath_start_deg=350.0,
        ath_span_deg=20.0,
        atv_top_deg=-10.0,
        atv_bottom_deg=10.0,
        px_per_deg=2.0,
    )
    image = render_strip(faces, strip)
    ath, _ = rig_angles(_decode(image[:, 20]))  # column 20 = ath 0.25
    assert np.abs(((ath + 180) % 360) - 180 - 0.25).max() < 1.5


def test_snap_edge_finds_a_vertical_step() -> None:
    edge = 37.3
    faces = _faces(
        lambda d: np.where(
            (rig_angles(d)[0] % 360.0 > edge)[:, None], 220.0, 40.0
        ).repeat(3, axis=1)
    )
    snap = snap_edge(faces, 36.4, window_deg=1.5, px_per_deg=20.0)
    assert snap.ath_deg == pytest.approx(edge, abs=0.15), f"Got {snap}"
    assert snap.clear
    assert snap.polarity == 1


def test_sample_colour_reads_the_patch() -> None:
    faces = _faces(lambda d: np.tile([200.0, 100.0, 50.0], (len(d), 1)))
    c = sample_colour(faces, 10.0, 5.0)
    assert c.rgb == (200, 100, 50)
    assert c.hex == "#c86432"
    assert srgb_to_oklab((255, 255, 255))[0] == pytest.approx(1.0, abs=1e-6)


def test_face_cache_loads_jpeg_and_evicts(tmp_path: Path) -> None:
    for scene in ("scene_1", "scene_2"):
        folder = tmp_path / scene
        folder.mkdir()
        for face in FACES:
            Image.new("RGB", (8, 8), (10, 20, 30)).save(folder / f"{face}.jpg")
    cache = FaceCache([tmp_path], capacity=1)
    assert cache.faces("scene_1")["f"].shape == (8, 8, 3)
    cache.faces("scene_2")
    assert list(cache._scenes) == ["scene_2"]
    with pytest.raises(FileNotFoundError, match="scene_9"):
        cache.faces("scene_9")


def test_building_code_and_outline_parsing() -> None:
    assert building_code("way/1", "İstanbul Aydın Üniversitesi A Binası") == "A"
    assert building_code("way/123456", None) == "3456"
    (b,) = parse_buildings(
        {
            "buildings": [
                {
                    "id": "way/9",
                    "name": None,
                    "height_m": 12.0,
                    "campus": False,
                    "outline": [[0, 0], [4, 0], [4, 4], [0, 0]],
                }
            ]
        }
    )
    assert b.outline.shape == (3, 2)  # closing vertex dropped


def test_tour_path_walks_arrows_both_ways() -> None:
    links = {"a": {"b": 0.0}, "c": {"b": 0.0}, "c2": {}}
    assert tour_path(links, "a", "c") == ["a", "b", "c"]
