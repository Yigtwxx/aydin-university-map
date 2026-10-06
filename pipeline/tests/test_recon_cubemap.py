import numpy as np
import pytest

from amap_pipeline.recon.cubemap import (
    CAM_FROM_RIG,
    FACES,
    TRANSFORMS,
    FloatArray,
    fit_transforms,
    forward,
    quaternion_wxyz,
    render_faces,
    rig_config,
)

SIZE = 64


def _colour(dirs: FloatArray) -> FloatArray:
    x, y, z = dirs[:, 0], dirs[:, 1], dirs[:, 2]
    return np.stack(
        [
            127.5 * (1 + np.sin(3 * x + 2 * y)),
            127.5 * (1 + np.sin(2 * y - 3 * z)),
            127.5 * (1 + np.cos(4 * z + x)),
        ],
        axis=1,
    )


@pytest.fixture(scope="module")
def faces() -> dict[str, FloatArray]:
    return render_faces(_colour, SIZE)


@pytest.mark.parametrize("face", FACES)
def test_cam_from_rig_is_proper_rotation(face: str) -> None:
    rotation = CAM_FROM_RIG[face]
    assert np.allclose(rotation @ rotation.T, np.eye(3)), f"{face} not orthonormal"
    assert np.isclose(np.linalg.det(rotation), 1.0), f"{face} has det != 1"


@pytest.mark.parametrize(
    ("face", "expected"),
    [("f", [0, 0, 1]), ("r", [1, 0, 0]), ("b", [0, 0, -1]), ("l", [-1, 0, 0]),
     ("u", [0, -1, 0]), ("d", [0, 1, 0])],
)  # fmt: skip
def test_forward_axes_match_krpano_layout(face: str, expected: list[int]) -> None:
    assert np.allclose(forward(face), expected), f"{face}: {forward(face)}"


def test_up_face_image_bottom_points_to_front() -> None:
    image_down = CAM_FROM_RIG["u"][1]
    assert np.allclose(image_down, [0, 0, 1]), f"Got {image_down}"


@pytest.mark.parametrize(
    ("face", "expected"),
    [
        ("r", [0.70710678, 0.0, -0.70710678, 0.0]),
        ("b", [0.0, 0.0, 1.0, 0.0]),
        ("l", [0.70710678, 0.0, 0.70710678, 0.0]),
        ("u", [0.70710678, -0.70710678, 0.0, 0.0]),
        ("d", [0.70710678, 0.70710678, 0.0, 0.0]),
    ],
)
def test_quaternion_wxyz_matches_expected_rig_rotation(
    face: str, expected: list[float]
) -> None:
    result = quaternion_wxyz(CAM_FROM_RIG[face])
    assert np.allclose(result, expected, atol=1e-6), f"{face}: {result}"


def test_fit_transforms_consistent_cube_keeps_identity(
    faces: dict[str, FloatArray],
) -> None:
    result = fit_transforms(faces)
    assert set(result.transforms.values()) == {"id"}, f"Got {result.transforms}"
    worst = max(result.edge_errors.values())
    assert worst < 2.0, f"Seams should be smooth, worst ratio {worst:.2f}"


@pytest.mark.parametrize(
    ("face", "stored_as", "expected_fix"),
    [("u", "rot90", "rot270"), ("d", "rot180", "rot180"), ("r", "flip", "flip")],
)
def test_fit_transforms_detects_misoriented_face(
    faces: dict[str, FloatArray], face: str, stored_as: str, expected_fix: str
) -> None:
    tampered = {**faces, face: TRANSFORMS[stored_as](faces[face])}
    result = fit_transforms(tampered)
    assert result.transforms[face] == expected_fix, f"Got {result.transforms}"


def test_fit_transforms_wrong_face_has_large_seam_error(
    faces: dict[str, FloatArray],
) -> None:
    tampered = {**faces, "b": faces["f"]}  # back face replaced by the front image
    worst = max(fit_transforms(tampered).edge_errors.values())
    assert worst > 3.0, f"Expected a broken seam, worst ratio {worst:.2f}"


def test_rig_config_has_reference_front_and_five_rotated_sensors() -> None:
    cameras = rig_config(1300)[0]["cameras"]
    assert isinstance(cameras, list)
    prefixes = [c["image_prefix"] for c in cameras]
    assert prefixes == [f"{f}/" for f in FACES], f"Got {prefixes}"
    assert cameras[0].get("ref_sensor") is True, "Front must be the reference sensor"
    assert all("cam_from_rig_rotation" in c for c in cameras[1:]), "Missing rotations"
    assert cameras[0]["camera_params"] == [650.0, 650.0, 650.0]
