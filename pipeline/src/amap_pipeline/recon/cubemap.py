"""Cube-face camera rig for krpano panoramas and the seam-continuity test.

Conventions (COLMAP camera axes: x right, y down, z forward). The rig frame is the
front-face camera frame. krpano faces seen from the panorama centre:

- ``f`` front (+z), ``r`` right (+x), ``b`` back (-z), ``l`` left (-x)
- ``u`` up (-y): image bottom edge touches the front face
- ``d`` down (+y): image top edge touches the front face

Each face is a 90° pinhole camera with f = W/2 and the principal point at the centre.
The seam test checks these assumptions on real panoramas: if a face is rotated or
flipped relative to the convention, its border pixels stop matching the
neighbouring faces. Any detected image transform is applied when images are
staged for SfM, so the rig rotations below stay fixed.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

FloatArray = NDArray[np.float64]

FACES: tuple[str, ...] = ("f", "r", "b", "l", "u", "d")

# Rows are the camera x (right), y (down), z (forward) axes in rig coordinates,
# i.e. the matrix maps rig vectors into camera coordinates.
CAM_FROM_RIG: dict[str, FloatArray] = {
    "f": np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64),
    "r": np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]], dtype=np.float64),
    "b": np.array([[-1, 0, 0], [0, 1, 0], [0, 0, -1]], dtype=np.float64),
    "l": np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=np.float64),
    "u": np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64),
    "d": np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64),
}

# The 8 in-plane image transforms (dihedral group). Each maps the stored image to
# the convention-aligned image.
TRANSFORMS: dict[str, Callable[[FloatArray], FloatArray]] = {
    "id": lambda a: a,
    "rot90": lambda a: np.rot90(a, 1),
    "rot180": lambda a: np.rot90(a, 2),
    "rot270": lambda a: np.rot90(a, 3),
    "flip": lambda a: a[:, ::-1],
    "flip_rot90": lambda a: np.rot90(a[:, ::-1], 1),
    "flip_rot180": lambda a: np.rot90(a[:, ::-1], 2),
    "flip_rot270": lambda a: np.rot90(a[:, ::-1], 3),
}

# Greedy order: each face is fitted against already-fixed neighbours.
_FIT_ORDER: tuple[str, ...] = ("r", "l", "u", "d", "b")


def forward(face: str) -> FloatArray:
    """Viewing direction of ``face`` in rig coordinates."""
    return CAM_FROM_RIG[face][2]


def adjacent(a: str, b: str) -> bool:
    return a != b and abs(float(forward(a) @ forward(b))) < 1e-9


def quaternion_wxyz(rotation: FloatArray) -> list[float]:
    """Unit quaternion [w, x, y, z] of a rotation matrix (w >= 0)."""
    m = rotation
    trace = float(np.trace(m))
    if trace > 0:
        s = 2.0 * np.sqrt(trace + 1.0)
        q = [
            0.25 * s,
            (m[2, 1] - m[1, 2]) / s,
            (m[0, 2] - m[2, 0]) / s,
            (m[1, 0] - m[0, 1]) / s,
        ]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        q = [
            (m[2, 1] - m[1, 2]) / s,
            0.25 * s,
            (m[0, 1] + m[1, 0]) / s,
            (m[0, 2] + m[2, 0]) / s,
        ]
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        q = [
            (m[0, 2] - m[2, 0]) / s,
            (m[0, 1] + m[1, 0]) / s,
            0.25 * s,
            (m[1, 2] + m[2, 1]) / s,
        ]
    else:
        s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        q = [
            (m[1, 0] - m[0, 1]) / s,
            (m[0, 2] + m[2, 0]) / s,
            (m[1, 2] + m[2, 1]) / s,
            0.25 * s,
        ]
    arr = np.asarray(q, dtype=np.float64)
    arr /= np.linalg.norm(arr)
    if arr[0] < 0:
        arr = -arr
    return [round(float(v), 8) + 0.0 for v in arr]


def project(face: str, dirs: FloatArray, size: int) -> FloatArray:
    """Pixel coordinates (u, v) of rig directions ``dirs`` (N, 3) in ``face``."""
    cam = dirs @ CAM_FROM_RIG[face].T
    half = size / 2.0
    u = half * cam[:, 0] / cam[:, 2] + half
    v = half * cam[:, 1] / cam[:, 2] + half
    return np.stack([u, v], axis=1)


def sample(image: FloatArray, uv: FloatArray) -> FloatArray:
    """Bilinear sample at pixel coordinates (pixel centres at i + 0.5)."""
    h, w = image.shape[:2]
    x = np.clip(uv[:, 0] - 0.5, 0.0, w - 1.0)
    y = np.clip(uv[:, 1] - 0.5, 0.0, h - 1.0)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (x - x0)[:, None]
    fy = (y - y0)[:, None]
    top = image[y0, x0] * (1 - fx) + image[y0, x1] * fx
    bottom = image[y1, x0] * (1 - fx) + image[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def edge_directions(a: str, b: str, n: int = 256) -> FloatArray:
    """Rig directions along the cube edge shared by faces ``a`` and ``b``."""
    na, nb = forward(a), forward(b)
    t = np.linspace(-0.9, 0.9, n)[:, None]
    return na + nb + t * np.cross(na, nb)


def seam_error(faces: Mapping[str, FloatArray], a: str, b: str) -> float:
    """Border mismatch of edge a|b relative to the natural pixel-to-pixel change.

    ~1 means the seam is as smooth as the image interior; large values mean the
    faces do not line up.
    """
    dirs = edge_directions(a, b)
    size = faces[a].shape[0]
    uv_a, uv_b = project(a, dirs, size), project(b, dirs, size)
    across = sample(faces[a], uv_a) - sample(faces[b], uv_b)
    # Natural change: step one pixel into face a, perpendicular to the edge.
    uv_in = project(a, dirs + _inward_offset(a, dirs, size), size)
    within = sample(faces[a], uv_a) - sample(faces[a], uv_in)
    baseline = float(np.mean(np.abs(within))) + 1.0
    return float(np.mean(np.abs(across))) / baseline


def _inward_offset(face: str, dirs: FloatArray, size: int) -> FloatArray:
    """Rig-space offset that moves edge points one pixel towards the face centre."""
    cam = dirs @ CAM_FROM_RIG[face].T
    centre_dir = np.zeros_like(cam)
    centre_dir[:, 2] = cam[:, 2]
    step = (centre_dir - cam) * (2.0 / size)
    return step @ CAM_FROM_RIG[face]


@dataclass(frozen=True, slots=True)
class SeamResult:
    transforms: dict[str, str]
    edge_errors: dict[str, float]
    margins: dict[str, float]


def fit_transforms(faces: Mapping[str, FloatArray]) -> SeamResult:
    """Pick, per face, the image transform that makes all seams continuous."""
    fixed: dict[str, FloatArray] = {"f": faces["f"]}
    chosen: dict[str, str] = {"f": "id"}
    margins: dict[str, float] = {}
    for face in _FIT_ORDER:
        neighbours = [n for n in fixed if adjacent(face, n)]
        scores: dict[str, float] = {}
        for name, transform in TRANSFORMS.items():
            candidate = {**fixed, face: transform(faces[face])}
            scores[name] = sum(seam_error(candidate, face, n) for n in neighbours)
        ranked = sorted(scores, key=scores.__getitem__)
        best, second = ranked[0], ranked[1]
        chosen[face] = best
        margins[face] = scores[second] / max(scores[best], 1e-9)
        fixed[face] = TRANSFORMS[best](faces[face])
    edges = {
        f"{a}|{b}": seam_error(fixed, a, b)
        for i, a in enumerate(FACES)
        for b in FACES[i + 1 :]
        if adjacent(a, b)
    }
    return SeamResult(chosen, edges, margins)


def load_faces(scene_dir: Path) -> dict[str, FloatArray]:
    faces: dict[str, FloatArray] = {}
    for face in FACES:
        with Image.open(scene_dir / f"{face}.jpg") as img:
            faces[face] = np.asarray(img.convert("RGB"), dtype=np.float64)
    return faces


def rig_config(face_size: int) -> list[dict[str, object]]:
    """COLMAP rig_config.json content for one cubemap rig."""
    focal = face_size / 2.0
    cameras: list[dict[str, object]] = []
    for face in FACES:
        camera: dict[str, object] = {
            "image_prefix": f"{face}/",
            "camera_model_name": "SIMPLE_PINHOLE",
            "camera_params": [focal, focal, focal],
        }
        if face == "f":
            camera["ref_sensor"] = True
        else:
            camera["cam_from_rig_rotation"] = quaternion_wxyz(CAM_FROM_RIG[face])
            camera["cam_from_rig_translation"] = [0.0, 0.0, 0.0]
        cameras.append(camera)
    return [{"cameras": cameras}]


def write_rig_config(path: Path, face_size: int, transforms: Mapping[str, str]) -> None:
    """Write the rig config plus the image transforms the staging step must apply."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rig_config(face_size), indent=2) + "\n", encoding="utf-8"
    )
    (path.parent / "face_transforms.json").write_text(
        json.dumps(dict(transforms), indent=2) + "\n", encoding="utf-8"
    )


def render_faces(
    colour: Callable[[FloatArray], FloatArray], size: int
) -> dict[str, FloatArray]:
    """Render the 6 faces of a panorama given as ``colour(directions) -> RGB``.

    Uses exactly the conventions above; handy for tests and debug previews.
    """
    centres = (np.arange(size, dtype=np.float64) + 0.5 - size / 2.0) / (size / 2.0)
    xs, ys = np.meshgrid(centres, centres)
    rays = np.stack([xs, ys, np.ones_like(xs)], axis=-1).reshape(-1, 3)
    faces: dict[str, FloatArray] = {}
    for face in FACES:
        dirs = rays @ CAM_FROM_RIG[face]  # camera -> rig
        dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
        faces[face] = colour(dirs).reshape(size, size, 3)
    return faces
