"""Dense textured mesh of one georeferenced SfM model with OpenMVS (CPU).

OpenMVS is an external tool (AGPL, ADR-0002/0008): its binaries are called as
separate processes from ``$OPENMVS_BIN`` and never imported or vendored.
Workspace: ``data/recon/<run>/dense_m<N>/``. Every stage writes one output
file and is skipped when that file exists (unless ``force``):

1. ``filter``     sparse/<N> as TXT without the nadir faces (``d``: tripod/car)
2. ``undistort``  ``colmap image_undistorter`` (pinhole faces: a plain copy)
3. ``interface``  ``InterfaceCOLMAP`` -> scene.mvs
4. ``densify``    ``DensifyPointCloud`` -> scene_dense.mvs + scene_dense.ply
5. ``mesh``       ``ReconstructMesh`` -> scene_mesh.ply
6. ``clean``      drop faces far from the dense cloud (sky blobs and hull
                  surfaces the graph cut invents) and tiny islands
                  -> scene_mesh_clean.ply
7. ``refine``     ``RefineMesh`` -> scene_mesh_refine.ply (optional)
8. ``tiles``      crop to the campus core and split into a quadtree of tile
                  meshes (still in model coordinates)
9. ``pack``       per tile ``TextureMesh`` -> GLB, bake the georeference into the
                  vertices (three.js frame), ``gltfpack -cc -tc`` -> output GLB;
                  a tile over the size limit is split again
   ``index.json`` per-tile file, bounds, triangles, texture size and quality

Tiles are cut *before* texturing so each tile carries only its own texture
atlas (cutting a textured mesh would copy the whole atlas into every tile).

Frames: model (SfM units) -> local ENU metres (x east, y north, z up; z = 0 is
the ground under the cameras) via the model's georeference -> three.js world
``(x, y, z) = (e, u, -n)``, the mapping of ``enuToWorld`` in the web app.
"""

import io
import json
import logging
import math
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from amap_pipeline.env import require_env
from amap_pipeline.recon.meshio import (
    FloatArray,
    IntArray,
    accessor_view,
    embed_images,
    glb_stats,
    read_glb,
    read_ply_mesh,
    read_ply_points,
    transform_glb,
    write_ply_mesh,
)

log = logging.getLogger(__name__)

MAX_TILE_BYTES = 25 * 1024 * 1024  # Cloudflare Pages per-file limit
HOUR_S = 3600.0
STAGES: tuple[str, ...] = (
    "filter",
    "undistort",
    "interface",
    "densify",
    "mesh",
    "clean",
    "refine",
    "tiles",
    "pack",
)

# ENU (e, n, u) -> three.js world (x = e, y = u, z = -n); a proper rotation.
ENU_TO_THREE: FloatArray = np.array(
    [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]], dtype=np.float64
)


# --- configuration and tools -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DenseConfig:
    run: str
    model: int
    resolution_level: int = 2
    number_views: int = 5  # DensifyPointCloud --number-views (0: all neighbours)
    fusion_depth_diff: float = 0.01  # --fusion-depth-diff-threshold
    refine: bool = True
    refine_resolution_level: int = 2
    refine_decimate: float = 0.0  # RefineMesh --decimate (0: auto, 1: keep all)
    texture_resolution_level: int = 0
    exclude_faces: tuple[str, ...] = ("d",)
    min_image_observations: int = 10  # faces with fewer sparse points are dropped
    min_point_distance_m: float = 0.3  # sparse points this close to a camera go
    max_support_m: float = 1.0  # faces farther from any dense point are dropped
    min_component_faces: int = 200
    crop_margin_m: float = 120.0
    z_range_m: tuple[float, float] = (-15.0, 100.0)
    max_tile_faces: int = 400_000
    min_tile_m: float = 8.0
    max_tile_bytes: int = MAX_TILE_BYTES
    max_texture_px: int = 8192
    coverage_cell_m: float = 2.0
    coverage_radius_m: float = 30.0  # coverage counts cells this close to a camera
    max_threads: int = 0
    timeout_s: float = 3 * HOUR_S
    force: bool = False  # redo every stage
    redo_from: str | None = None  # redo this stage and the later ones


@dataclass(frozen=True, slots=True)
class Tools:
    """External binaries: OpenMVS directory, gltfpack and the COLMAP CLI."""

    openmvs_dir: Path
    gltfpack: Path
    colmap: str = "colmap"

    @classmethod
    def from_env(cls) -> "Tools":
        return cls(
            openmvs_dir=Path(require_env("OPENMVS_BIN")),
            gltfpack=Path(require_env("GLTFPACK_BIN")),
            colmap=os.environ.get("COLMAP_BIN", "colmap"),
        )

    def openmvs(self, tool: str) -> str:
        return str(self.openmvs_dir / tool)


# --- georeference -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Similarity3D:
    """``out = matrix @ p + translation`` with matrix = scale * rotation."""

    matrix: FloatArray
    translation: FloatArray

    @property
    def scale(self) -> float:
        return float(np.cbrt(np.linalg.det(self.matrix)))

    @property
    def rotation(self) -> FloatArray:
        return self.matrix / self.scale

    def apply(self, points: FloatArray) -> FloatArray:
        return points @ self.matrix.T + self.translation

    def then(self, rotation: FloatArray) -> "Similarity3D":
        """This transform followed by a pure rotation."""
        return Similarity3D(rotation @ self.matrix, rotation @ self.translation)


def model_to_enu(georef: Mapping[str, Any]) -> Similarity3D:
    """3D similarity model -> ENU from a ``georef_m<N>.json`` document.

    ``levelled = basis @ p``; ``xy = s R(yaw) levelled_xy + shift``;
    ``z = s (levelled_z - ground_z_model)`` (as written by ``amap georef``).
    """
    basis = np.asarray(georef["basis_levelled_from_model"], dtype=np.float64)
    sim = georef["similarity"]
    scale = float(sim["scale_m_per_unit"])
    yaw = math.radians(float(sim["yaw_deg"]))
    c, s = math.cos(yaw), math.sin(yaw)
    turn = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    shift = sim["shift_m"]
    translation = np.array(
        [shift[0], shift[1], -scale * float(georef["ground_z_model"])], np.float64
    )
    return Similarity3D(scale * turn @ basis, translation)


def model_to_three(georef: Mapping[str, Any]) -> Similarity3D:
    return model_to_enu(georef).then(ENU_TO_THREE)


def enu_to_three(points: FloatArray) -> FloatArray:
    return points @ ENU_TO_THREE.T


def three_to_enu(points: FloatArray) -> FloatArray:
    return points @ ENU_TO_THREE


# --- sparse model filtering ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class FilteredModel:
    cameras: str
    images: str
    points3d: str
    kept_images: int
    dropped_images: int
    kept_points: int
    dropped_points: int


def _data_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.startswith("#")]


def camera_centre(header: Sequence[str]) -> FloatArray:
    """Centre ``-R^T t`` of a COLMAP images.txt header (QW QX QY QZ TX TY TZ)."""
    w, x, y, z, tx, ty, tz = (float(v) for v in header[1:8])
    rot = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )
    return -rot.T @ np.array([tx, ty, tz])


def filter_text_model(
    cameras_txt: str,
    images_txt: str,
    points3d_txt: str,
    exclude_faces: Sequence[str],
    min_observations: int = 0,
    min_point_distance: float = 0.0,
) -> FilteredModel:
    """Drop the images of ``exclude_faces`` from a COLMAP TXT model.

    Images with fewer than ``min_observations`` 3D points are dropped too: a
    rig registers every face of a panorama, but a face without sparse points
    has no depth range and crashes DensifyPointCloud. Points closer than
    ``min_point_distance`` (model units) to an observing camera are dropped:
    such degenerate triangulations give a neighbour view an absurd scale and
    DensifyPointCloud tries to allocate exabytes.
    Tracks lose the dropped images; points left with < 2 observations are
    removed and their 2D references reset to -1, so the model stays consistent.
    Rigs/frames are not written: COLMAP reads such a model as one trivial rig
    per camera, and OpenMVS only needs per-image poses.
    """
    prefixes = tuple(f"{face}/" for face in exclude_faces)
    image_lines = _data_lines(images_txt)
    if len(image_lines) % 2 == 1 and image_lines[-1] == "":
        image_lines = image_lines[:-1]
    observations: dict[int, int] = {}
    for line in _data_lines(points3d_txt):
        track = line.split()[8:]
        for image_id in track[::2]:
            observations[int(image_id)] = observations.get(int(image_id), 0) + 1
    kept: list[tuple[list[str], str]] = []
    dropped_ids: set[int] = set()
    for header, points2d in zip(image_lines[::2], image_lines[1::2], strict=True):
        parts = header.split()
        image_id = int(parts[0])
        if (
            parts[9].startswith(prefixes)
            or observations.get(image_id, 0) < min_observations
        ):
            dropped_ids.add(image_id)
        else:
            kept.append((parts, points2d))

    centres = {int(parts[0]): camera_centre(parts) for parts, _ in kept}
    point_rows: list[str] = []
    removed_points: set[int] = set()
    for line in _data_lines(points3d_txt):
        if not line.strip():
            continue
        parts = line.split()
        track = parts[8:]
        pairs = [
            (track[i], track[i + 1])
            for i in range(0, len(track), 2)
            if int(track[i]) not in dropped_ids
        ]
        xyz = np.array([float(v) for v in parts[1:4]])
        too_close = min_point_distance > 0 and any(
            np.linalg.norm(xyz - centres[int(image_id)]) < min_point_distance
            for image_id, _ in pairs
        )
        if len(pairs) < 2 or too_close:
            removed_points.add(int(parts[0]))
            continue
        point_rows.append(" ".join(parts[:8] + [v for pair in pairs for v in pair]))

    image_rows: list[str] = []
    used_cameras: set[str] = set()
    for parts, points2d in kept:
        used_cameras.add(parts[8])
        tokens = points2d.split()
        for i in range(2, len(tokens), 3):
            if tokens[i] != "-1" and int(tokens[i]) in removed_points:
                tokens[i] = "-1"
        image_rows.append(" ".join(parts))
        image_rows.append(" ".join(tokens))
    camera_rows = [
        line
        for line in _data_lines(cameras_txt)
        if line.strip() and line.split()[0] in used_cameras
    ]
    return FilteredModel(
        cameras="\n".join(camera_rows) + "\n",
        images="\n".join(image_rows) + "\n",
        points3d="\n".join(point_rows) + "\n",
        kept_images=len(kept),
        dropped_images=len(dropped_ids),
        kept_points=len(point_rows),
        dropped_points=len(removed_points),
    )


# --- command lines ------------------------------------------------------------------


def model_converter_cmd(colmap: str, src: Path, dst: Path) -> list[str]:
    return [
        colmap, "model_converter",
        "--input_path", str(src),
        "--output_path", str(dst),
        "--output_type", "TXT",
    ]  # fmt: skip


def undistorter_cmd(colmap: str, images: Path, sparse: Path, out: Path) -> list[str]:
    return [
        colmap, "image_undistorter",
        "--image_path", str(images),
        "--input_path", str(sparse),
        "--output_path", str(out),
        "--output_type", "COLMAP",
    ]  # fmt: skip


def interface_cmd(tools: Tools) -> list[str]:
    """Run inside the dense workspace; ``--image-folder`` is relative to ``-i``."""
    return [
        tools.openmvs("InterfaceCOLMAP"),
        "-i", "undistorted",
        "-o", "scene.mvs",
        "--image-folder", "images",
    ]  # fmt: skip


def densify_cmd(tools: Tools, cfg: DenseConfig) -> list[str]:
    # ROI estimation, ROI cropping and tower mode target object/aerial
    # captures; a street-level walk through a campus needs all of the scene.
    return [
        tools.openmvs("DensifyPointCloud"),
        "scene.mvs",
        "-o", "scene_dense.mvs",
        "--resolution-level", str(cfg.resolution_level),
        "--max-threads", str(cfg.max_threads),
        "--estimate-roi", "0",
        "--crop-to-roi", "0",
        "--tower-mode", "0",
        "--number-views", str(cfg.number_views),
        "--fusion-depth-diff-threshold", str(cfg.fusion_depth_diff),
    ]  # fmt: skip


def reconstruct_cmd(tools: Tools, cfg: DenseConfig) -> list[str]:
    return [
        tools.openmvs("ReconstructMesh"),
        "scene_dense.mvs",
        "-p", "scene_dense.ply",
        "-o", "scene_mesh.mvs",
        "--crop-to-roi", "0",
        "--max-threads", str(cfg.max_threads),
    ]  # fmt: skip


def refine_cmd(tools: Tools, cfg: DenseConfig) -> list[str]:
    return [
        tools.openmvs("RefineMesh"),
        "scene.mvs",
        "-m", "scene_mesh_clean.ply",
        "-o", "scene_mesh_refine.mvs",
        "--resolution-level", str(cfg.refine_resolution_level),
        "--decimate", str(cfg.refine_decimate),
        "--max-threads", str(cfg.max_threads),
    ]  # fmt: skip


def texture_cmd(tools: Tools, cfg: DenseConfig, mesh: str, out_mvs: str) -> list[str]:
    """TextureMesh on ``scene.mvs`` (full-size images; ``scene_dense.mvs`` stores
    them at the densify resolution). Holes were closed on the whole mesh
    already; closing them again per tile would patch the cut borders.

    ``out_mvs`` must have no directory part: OpenMVS prefixes the texture path
    with the output directory twice.
    """
    if "/" in out_mvs:
        raise ValueError("TextureMesh output must be a bare file name")
    return [
        tools.openmvs("TextureMesh"),
        "scene.mvs",
        "-m", mesh,
        "-o", out_mvs,
        "--export-type", "glb",
        "--resolution-level", str(cfg.texture_resolution_level),
        "--max-texture-size", str(cfg.max_texture_px),
        "--close-holes", "0",
        "--decimate", "1",
        # Seam levelling in the 2.4.0 macOS arm64 build blackens the patches
        # (global) or paints their borders (local); see ADR-0008.
        "--global-seam-leveling", "0",
        "--local-seam-leveling", "0",
        "--max-threads", str(cfg.max_threads),
    ]  # fmt: skip


def gltfpack_cmd(
    tools: Tools, src: Path, dst: Path, texture_limit_px: int | None = None
) -> list[str]:
    cmd = [str(tools.gltfpack), "-i", str(src), "-o", str(dst), "-cc", "-tc"]
    if texture_limit_px:
        cmd += ["-tl", str(texture_limit_px)]
    return cmd


# --- subprocesses ---------------------------------------------------------------------


class ToolError(RuntimeError):
    """An external tool failed or timed out; the message carries its log tail."""


def _cpu_seconds(pid: int) -> float | None:
    """Accumulated CPU time of a process (``ps``; macOS and Linux)."""
    out = subprocess.run(
        ["ps", "-o", "time=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not out:
        return None
    days, _, clock = out.rpartition("-")
    seconds = 0.0
    for part in clock.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds + (int(days) * 86400 if days else 0)


def run_logged(
    cmd: Sequence[str],
    log_path: Path,
    timeout_s: float,
    cwd: Path | None = None,
    stall_s: float = 1800.0,
    poll_s: float = 15.0,
) -> float:
    """Run ``cmd`` with its output in ``log_path``; returns the wall-clock seconds.

    Besides the overall ``timeout_s`` the tool is killed when it neither writes
    to its log nor uses CPU for ``stall_s`` (OpenMVS can deadlock on tiny
    meshes).
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    name = Path(cmd[0]).name
    with log_path.open("w", encoding="utf-8") as fh:
        fh.write(f"$ {' '.join(cmd)}\n")
        fh.flush()
        proc = subprocess.Popen(list(cmd), stdout=fh, stderr=subprocess.STDOUT, cwd=cwd)
        last_size, last_cpu, last_progress = -1, -1.0, time.perf_counter()
        while True:
            try:
                proc.wait(timeout=poll_s)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.perf_counter()
            size = log_path.stat().st_size
            cpu = _cpu_seconds(proc.pid)
            if size != last_size or (cpu is not None and cpu > last_cpu + 1.0):
                last_size, last_cpu, last_progress = size, cpu or last_cpu, now
            reason = None
            if now - start > timeout_s:
                reason = f"timed out after {timeout_s:.0f} s"
            elif now - last_progress > stall_s:
                reason = f"stalled for {stall_s:.0f} s (no log output, no CPU)"
            if reason:
                proc.kill()
                proc.wait()
                raise ToolError(f"{name} {reason} ({log_path})")
    seconds = time.perf_counter() - start
    if proc.returncode != 0:
        tail = "\n".join(
            log_path.read_text("utf-8", errors="replace").splitlines()[-25:]
        )
        raise ToolError(f"{name} exited with {proc.returncode} ({log_path}):\n{tail}")
    return seconds


# --- mesh geometry: crop, tiles, quality ----------------------------------------


@dataclass(frozen=True, slots=True)
class Rect:
    """Axis-aligned ENU rectangle (east/north metres)."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def size(self) -> float:
        return max(self.x1 - self.x0, self.y1 - self.y0)

    def quadrants(self) -> tuple["Rect", "Rect", "Rect", "Rect"]:
        """South-west, south-east, north-west, north-east."""
        xm, ym = (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2
        return (
            Rect(self.x0, self.y0, xm, ym),
            Rect(xm, self.y0, self.x1, ym),
            Rect(self.x0, ym, xm, self.y1),
            Rect(xm, ym, self.x1, self.y1),
        )


def crop_rect(cameras_xy: FloatArray, margin_m: float) -> Rect:
    """Camera bounding box grown by ``margin_m``, as a square (quadtree root)."""
    lo = cameras_xy.min(axis=0) - margin_m
    hi = cameras_xy.max(axis=0) + margin_m
    centre = (lo + hi) / 2
    half = float(max(hi - lo)) / 2
    return Rect(centre[0] - half, centre[1] - half, centre[0] + half, centre[1] + half)


def crop_faces(
    centroids_enu: FloatArray,
    cameras_xy: FloatArray,
    margin_m: float,
    z_range_m: tuple[float, float],
) -> NDArray[np.bool_]:
    """Faces whose centroid lies in the camera bbox + margin and the z range."""
    lo = cameras_xy.min(axis=0) - margin_m
    hi = cameras_xy.max(axis=0) + margin_m
    x, y, z = centroids_enu[:, 0], centroids_enu[:, 1], centroids_enu[:, 2]
    return (
        (x >= lo[0])
        & (x <= hi[0])
        & (y >= lo[1])
        & (y <= hi[1])
        & (z >= z_range_m[0])
        & (z <= z_range_m[1])
    )


def quadrant_index(centroids_xy: FloatArray, rect: Rect) -> NDArray[np.int64]:
    """Child 0..3 of ``rect.quadrants()`` for each centroid (a strict partition)."""
    xm, ym = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
    east = (centroids_xy[:, 0] >= xm).astype(np.int64)
    north = (centroids_xy[:, 1] >= ym).astype(np.int64)
    return east + 2 * north


@dataclass(frozen=True, slots=True)
class Tile:
    code: str  # quadtree path: "r", "r0", "r03", ...
    rect: Rect
    faces: IntArray  # indices into the cropped mesh's faces


def quadtree(
    centroids_xy: FloatArray,
    root: Rect,
    max_faces: int,
    min_size_m: float,
    code: str = "r",
    faces: IntArray | None = None,
) -> list[Tile]:
    """Split until a tile has <= ``max_faces`` faces or reaches ``min_size_m``."""
    index = np.arange(len(centroids_xy)) if faces is None else faces
    leaves: list[Tile] = []
    stack = [(code, root, index)]
    while stack:
        name, rect, members = stack.pop()
        if len(members) == 0:
            continue
        if len(members) <= max_faces or rect.size / 2 < min_size_m:
            leaves.append(Tile(name, rect, members))
            continue
        child = quadrant_index(centroids_xy[members], rect)
        for k, sub in enumerate(rect.quadrants()):
            stack.append((f"{name}{k}", sub, members[child == k]))
    return sorted(leaves, key=lambda t: t.code)


def submesh(
    vertices: FloatArray, faces: IntArray, face_index: IntArray
) -> tuple[FloatArray, IntArray]:
    """The faces ``face_index`` with only their vertices, re-indexed."""
    chosen = faces[face_index]
    used, inverse = np.unique(chosen.ravel(), return_inverse=True)
    return vertices[used], inverse.reshape(-1, 3).astype(np.int64)


def supported_faces(
    vertices: FloatArray, faces: IntArray, points: FloatArray, max_dist: float
) -> NDArray[np.bool_]:
    """Faces whose centroid lies within ``max_dist`` of a dense point."""
    from scipy.spatial import KDTree

    if len(faces) == 0:
        return np.zeros(0, dtype=bool)
    dist, _ = KDTree(points).query(vertices[faces].mean(axis=1), workers=-1)
    return np.asarray(dist <= max_dist)


def large_components(faces: IntArray, min_faces: int) -> NDArray[np.bool_]:
    """Faces in vertex-connected components with at least ``min_faces`` faces."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    if len(faces) == 0:
        return np.zeros(0, dtype=bool)
    n = int(faces.max()) + 1
    rows = np.concatenate([faces[:, 0], faces[:, 1]])
    cols = np.concatenate([faces[:, 1], faces[:, 2]])
    graph = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
    _, labels = connected_components(graph, directed=False)
    face_label = labels[faces[:, 0]]
    sizes = np.bincount(face_label)
    return sizes[face_label] >= min_faces


def boundary_edges_per_face(faces: IntArray) -> IntArray:
    """How many of each triangle's edges are open (used by one face only)."""
    if len(faces) == 0:
        return np.zeros(0, np.int64)
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges.sort(axis=1)
    _, inverse, counts = np.unique(
        edges, axis=0, return_inverse=True, return_counts=True
    )
    open_edge = (counts[inverse.ravel()] == 1).astype(np.int64)
    return open_edge.reshape(3, -1).sum(axis=0)


def coverage_share(
    points_xy: FloatArray,
    rect: Rect,
    cell_m: float,
    near_xy: FloatArray | None = None,
    radius_m: float = 30.0,
) -> float | None:
    """Share of the ``cell_m`` cells of ``rect`` that contain mesh samples.

    With ``near_xy`` (camera positions) only cells within ``radius_m`` of a
    camera count, i.e. the surroundings the panoramas could see; None when the
    tile has no such cell.
    """
    cols = max(1, math.ceil((rect.x1 - rect.x0) / cell_m))
    rows = max(1, math.ceil((rect.y1 - rect.y0) / cell_m))
    ij = np.floor((points_xy - [rect.x0, rect.y0]) / cell_m).astype(np.int64)
    ok = (ij[:, 0] >= 0) & (ij[:, 0] < cols) & (ij[:, 1] >= 0) & (ij[:, 1] < rows)
    occupied = np.zeros(rows * cols, dtype=bool)
    occupied[ij[ok, 1] * cols + ij[ok, 0]] = True
    eligible = np.ones(rows * cols, dtype=bool)
    if near_xy is not None:
        cx = rect.x0 + (np.arange(cols) + 0.5) * cell_m
        cy = rect.y0 + (np.arange(rows) + 0.5) * cell_m
        gx, gy = np.meshgrid(cx, cy)
        centres = np.column_stack([gx.ravel(), gy.ravel()])
        eligible = np.zeros(rows * cols, dtype=bool)
        for cam in near_xy:
            eligible |= np.hypot(*(centres - cam).T) <= radius_m
    if not eligible.any():
        return None
    return float((occupied & eligible).sum()) / float(eligible.sum())


# --- the run --------------------------------------------------------------------------


@dataclass(slots=True)
class DenseReport:
    run: str
    model: int
    config: dict[str, Any] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path, run: str, model: int) -> "DenseReport":
        report = cls(run, model)
        if path.is_file():
            old = json.loads(path.read_text("utf-8"))
            report.seconds.update(old.get("seconds", {}))
            report.stats.update(old.get("stats", {}))
        return report

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", "utf-8")


@dataclass(frozen=True, slots=True)
class ModelPaths:
    dense: Path
    out_root: Path

    @property
    def logs(self) -> Path:
        return self.dense / "logs"

    @property
    def tiles(self) -> Path:
        return self.dense / "tiles"

    @property
    def report(self) -> Path:
        return self.dense / "dense_report.json"

    def out_dir(self, run: str, model: int) -> Path:
        return self.out_root / f"{run}_m{model}"


class DenseRunner:
    """Runs the stages for one model; see the module docstring."""

    def __init__(
        self,
        cfg: DenseConfig,
        workspace: Path,
        out_root: Path,
        georef: Mapping[str, Any],
        tools: Tools,
    ) -> None:
        self.cfg = cfg
        self.workspace = workspace
        self.paths = ModelPaths(workspace / f"dense_m{cfg.model}", out_root)
        self.georef = georef
        self.tools = tools
        self.to_enu = model_to_enu(georef)
        self.to_three = self.to_enu.then(ENU_TO_THREE)
        self.paths.dense.mkdir(parents=True, exist_ok=True)
        self.report = DenseReport.load(self.paths.report, cfg.run, cfg.model)
        self.report.config = asdict(cfg)
        self._packed_any = False

    # -- helpers --
    def _forced(self, stage: str) -> bool:
        redo = self.cfg.redo_from
        return self.cfg.force or (
            redo is not None and STAGES.index(stage) >= STAGES.index(redo)
        )

    def _stage(self, name: str, output: Path, body: Callable[[], None]) -> None:
        if output.exists() and not self._forced(name):
            log.info("stage %s: done earlier (%s)", name, output.name)
            return
        log.info("stage %s: start", name)
        start = time.perf_counter()
        body()
        if not output.exists():
            raise ToolError(f"stage {name} finished without {output}")
        self.report.seconds[name] = round(time.perf_counter() - start, 1)
        self.report.save(self.paths.report)
        log.info("stage %s: %.1f s", name, self.report.seconds[name])

    def _tool(
        self, name: str, cmd: Sequence[str], timeout_s: float | None = None
    ) -> None:
        run_logged(
            cmd,
            self.paths.logs / f"{name}.log",
            timeout_s or self.cfg.timeout_s,
            cwd=self.paths.dense,
        )

    def check_georef(self, sparse: Path) -> float:
        """Median distance of transformed camera centres to the georef scenes (m)."""
        import pycolmap

        from amap_pipeline.recon.evaluate import extract_poses

        rec = pycolmap.Reconstruction(sparse)
        scenes = self.georef["scenes"]
        errors = []
        for pose in extract_poses(rec):
            if pose.scene in scenes:
                enu = self.to_enu.apply(pose.center[None, :])[0]
                ref = scenes[pose.scene]
                errors.append(
                    float(np.linalg.norm(enu - [ref["x"], ref["y"], ref["height_m"]]))
                )
        return float(np.median(errors)) if errors else math.inf

    # -- stages --
    def run(self, until: str | None = None) -> DenseReport:
        """Run every stage in order (``until``: stop after that stage)."""
        cfg, d = self.cfg, self.paths.dense
        sparse = self.workspace / "sparse" / str(cfg.model)
        georef_err = self.check_georef(sparse)
        self.report.stats["georef_camera_check_m"] = round(georef_err, 4)
        log.info("georef check: camera centres within %.4f m (median)", georef_err)
        if georef_err > 0.05:
            raise ValueError(
                f"georeference does not reproduce the cameras ({georef_err} m)"
            )
        mesh = d / ("scene_mesh_refine.ply" if cfg.refine else "scene_mesh_clean.ply")
        undistort = undistorter_cmd(
            self.tools.colmap,
            (self.workspace / "images").resolve(),
            (d / "sparse_nadir_free").resolve(),
            (d / "undistorted").resolve(),
        )
        steps: dict[str, tuple[Path, Callable[[], None]]] = {
            "filter": (d / "sparse_nadir_free" / "points3D.txt", self._filter),
            "undistort": (
                d / "undistorted" / "sparse" / "cameras.bin",
                lambda: self._undistort(undistort),
            ),
            "interface": (
                d / "scene.mvs",
                lambda: self._tool("interface", interface_cmd(self.tools)),
            ),
            "densify": (d / "scene_dense.ply", self._densify),
            "mesh": (
                d / "scene_mesh.ply",
                lambda: self._tool("mesh", reconstruct_cmd(self.tools, cfg)),
            ),
            "clean": (d / "scene_mesh_clean.ply", self._clean),
            "refine": (
                d / "scene_mesh_refine.ply",
                lambda: self._tool("refine", refine_cmd(self.tools, cfg)),
            ),
            "tiles": (self.paths.tiles / "tiles.json", lambda: self._split(mesh)),
        }
        for name in STAGES:
            if name == "refine" and not cfg.refine:
                continue
            if name == "pack":
                self._texture_and_pack()
            else:
                output, body = steps[name]
                self._stage(name, output, body)
            if name == until:
                log.info("stopping after stage %s", name)
                break
        self.report.save(self.paths.report)
        return self.report

    def _filter(self) -> None:
        d = self.paths.dense
        txt = d / "sparse_txt"
        txt.mkdir(parents=True, exist_ok=True)
        self._tool(
            "model_converter",
            model_converter_cmd(
                self.tools.colmap,
                (self.workspace / "sparse" / str(self.cfg.model)).resolve(),
                txt.resolve(),
            ),
            timeout_s=600,
        )
        filtered = filter_text_model(
            (txt / "cameras.txt").read_text("utf-8"),
            (txt / "images.txt").read_text("utf-8"),
            (txt / "points3D.txt").read_text("utf-8"),
            self.cfg.exclude_faces,
            self.cfg.min_image_observations,
            self.cfg.min_point_distance_m / self.to_enu.scale,
        )
        out = d / "sparse_nadir_free"
        out.mkdir(parents=True, exist_ok=True)
        (out / "cameras.txt").write_text(filtered.cameras, "utf-8")
        (out / "images.txt").write_text(filtered.images, "utf-8")
        (out / "points3D.txt").write_text(filtered.points3d, "utf-8")
        self.report.stats["filter"] = {
            "kept_images": filtered.kept_images,
            "dropped_images": filtered.dropped_images,
            "kept_points": filtered.kept_points,
            "dropped_points": filtered.dropped_points,
        }
        log.info(
            "filter: %d images kept, %d dropped (nadir or < %d points), %d/%d points",
            filtered.kept_images,
            filtered.dropped_images,
            self.cfg.min_image_observations,
            filtered.kept_points,
            filtered.kept_points + filtered.dropped_points,
        )

    def _undistort(self, cmd: Sequence[str]) -> None:
        # image_undistorter aborts when a copied image already exists.
        shutil.rmtree(self.paths.dense / "undistorted", ignore_errors=True)
        self._tool("undistort", cmd)

    def _densify(self) -> None:
        # DensifyPointCloud reuses depth maps it finds; stale ones from another
        # resolution level would be fused as if they were new.
        for stale in self.paths.dense.glob("depth*.dmap"):
            stale.unlink()
        self._tool("densify", densify_cmd(self.tools, self.cfg))
        # The fused cloud is the result; the depth maps take ~1 GB per model.
        for done in self.paths.dense.glob("depth*.dmap"):
            done.unlink()

    def _clean(self) -> None:
        d, cfg = self.paths.dense, self.cfg
        vertices, faces = read_ply_mesh(d / "scene_mesh.ply")
        points = read_ply_points(d / "scene_dense.ply")
        keep = supported_faces(
            vertices, faces, points, cfg.max_support_m / self.to_enu.scale
        )
        v_sup, f_sup = submesh(vertices, faces, np.flatnonzero(keep))
        big = large_components(f_sup, cfg.min_component_faces)
        v_out, f_out = submesh(v_sup, f_sup, np.flatnonzero(big))
        write_ply_mesh(d / "scene_mesh_clean.ply", v_out, f_out)
        self.report.stats["clean"] = {
            "faces_in": len(faces),
            "unsupported_removed": int((~keep).sum()),
            "island_faces_removed": int((~big).sum()),
            "faces_out": len(f_out),
        }
        log.info(
            "clean: %d faces -> %d (%d unsupported > %.1f m, %d in islands)",
            len(faces),
            len(f_out),
            int((~keep).sum()),
            cfg.max_support_m,
            int((~big).sum()),
        )

    def _cameras_xy(self) -> FloatArray:
        scenes = self.georef["scenes"]
        return np.array([[s["x"], s["y"]] for s in scenes.values()], np.float64)

    def _split(self, mesh_path: Path) -> None:
        cfg, tiles_dir = self.cfg, self.paths.tiles
        vertices, faces = read_ply_mesh(mesh_path)
        if mesh_path.name != "scene_mesh_clean.ply":
            # RefineMesh can grow spikes far from the data; drop them again.
            points = read_ply_points(self.paths.dense / "scene_dense.ply")
            keep = supported_faces(
                vertices, faces, points, cfg.max_support_m / self.to_enu.scale
            )
            vertices, faces = submesh(vertices, faces, np.flatnonzero(keep))
            big = large_components(faces, cfg.min_component_faces)
            vertices, faces = submesh(vertices, faces, np.flatnonzero(big))
            self.report.stats["refine_clean"] = {
                "unsupported_removed": int((~keep).sum()),
                "island_faces_removed": int((~big).sum()),
            }
            log.info(
                "refined mesh: %d unsupported faces and %d island faces removed",
                int((~keep).sum()),
                int((~big).sum()),
            )
        centroids = self.to_enu.apply(vertices)[faces].mean(axis=1)
        cams = self._cameras_xy()
        keep = crop_faces(centroids, cams, cfg.crop_margin_m, cfg.z_range_m)
        log.info(
            "crop: %d of %d faces inside the campus core (+%.0f m)",
            int(keep.sum()),
            len(faces),
            cfg.crop_margin_m,
        )
        v_crop, f_crop = submesh(vertices, faces, np.flatnonzero(keep))
        enu = self.to_enu.apply(v_crop)
        # Open edges of the whole cropped mesh: holes and the outer border, but
        # not the tile cuts made below.
        open_edges = boundary_edges_per_face(f_crop)
        shutil.rmtree(tiles_dir, ignore_errors=True)
        tiles_dir.mkdir(parents=True)
        write_ply_mesh(tiles_dir / "cropped.ply", v_crop, f_crop)
        np.save(tiles_dir / "open_edges.npy", open_edges)
        tiles = quadtree(
            enu[f_crop].mean(axis=1)[:, :2],
            crop_rect(cams, cfg.crop_margin_m),
            cfg.max_tile_faces,
            cfg.min_tile_m,
        )
        meta = {
            t.code: self._write_tile(t.code, t.rect, t.faces, v_crop, f_crop)
            for t in tiles
        }
        self.report.stats["mesh"] = {
            "faces_total": len(faces),
            "faces_cropped": len(f_crop),
            "vertices_cropped": len(v_crop),
            "hole_ratio": round(float(open_edges.sum()) / max(1, 3 * len(f_crop)), 5),
            "tiles_initial": len(tiles),
        }
        _write_json(tiles_dir / "tiles.json", meta)

    def _write_tile(
        self,
        code: str,
        rect: Rect,
        face_index: IntArray,
        vertices: FloatArray,
        faces: IntArray,
    ) -> dict[str, Any]:
        """Write one tile (model coordinates) and its quality numbers."""
        v_sub, f_sub = submesh(vertices, faces, face_index)
        write_ply_mesh(self.paths.tiles / f"{code}.ply", v_sub, f_sub)
        np.save(self.paths.tiles / f"{code}.faces.npy", face_index)
        open_edges = np.load(self.paths.tiles / "open_edges.npy")
        enu = self.to_enu.apply(v_sub)
        samples = np.concatenate([enu, enu[f_sub].mean(axis=1)])[:, :2]
        return {
            "rect_enu": [rect.x0, rect.y0, rect.x1, rect.y1],
            "faces": len(face_index),
            "coverage_share": _round(
                coverage_share(
                    samples,
                    rect,
                    self.cfg.coverage_cell_m,
                    self._cameras_xy(),
                    self.cfg.coverage_radius_m,
                )
            ),
            "hole_ratio": round(
                float(open_edges[face_index].sum()) / max(1, 3 * len(face_index)), 5
            ),
        }

    def _resplit(self, code: str, meta: dict[str, Any]) -> list[str]:
        """Replace tile ``code`` by its non-empty quadrants (in ``meta``)."""
        rect = Rect(*meta[code]["rect_enu"])
        if rect.size / 2 < self.cfg.min_tile_m:
            return []
        cropped_v, cropped_f = read_ply_mesh(self.paths.tiles / "cropped.ply")
        index = np.load(self.paths.tiles / f"{code}.faces.npy")
        cent = self.to_enu.apply(cropped_v)[cropped_f[index]].mean(axis=1)[:, :2]
        child = quadrant_index(cent, rect)
        names: list[str] = []
        for k, sub in enumerate(rect.quadrants()):
            members = index[child == k]
            if len(members):
                name = f"{code}{k}"
                meta[name] = self._write_tile(name, sub, members, cropped_v, cropped_f)
                names.append(name)
        del meta[code]
        for suffix in (".ply", ".faces.npy", "_tex.glb", "_world.glb"):
            (self.paths.tiles / f"{code}{suffix}").unlink(missing_ok=True)
        _write_json(self.paths.tiles / "tiles.json", meta)
        return names

    def _texture_and_pack(self) -> None:
        tiles_dir = self.paths.tiles
        meta: dict[str, Any] = json.loads((tiles_dir / "tiles.json").read_text("utf-8"))
        out_dir = self.paths.out_dir(self.cfg.run, self.cfg.model)
        if self._forced("pack"):
            shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        log.info("stage pack: %d tiles", len(meta))
        start = time.perf_counter()
        done: dict[str, int] = {}
        queue = sorted(meta)
        while queue:
            code = queue.pop(0)
            packed = self._process_tile(code, out_dir)
            size = packed.stat().st_size
            if size <= self.cfg.max_tile_bytes:
                done[code] = size
                continue
            children = self._resplit(code, meta)
            if children:
                log.info(
                    "tile %s: %.1f MiB > limit, split into %s",
                    code,
                    size / 2**20,
                    children,
                )
                packed.unlink()
                queue = sorted(children) + queue
                continue
            # Smallest tile still too big: limit the texture size instead.
            log.info("tile %s: %.1f MiB > limit, halving textures", code, size / 2**20)
            self._pack(code, out_dir, texture_limit_px=self.cfg.max_texture_px // 2)
            size = packed.stat().st_size
            if size > self.cfg.max_tile_bytes:
                raise ToolError(f"tile {code} stays above the size limit ({size} B)")
            done[code] = size
        for stale in out_dir.glob("*.glb"):
            if stale.stem not in done:
                stale.unlink()
        seconds = round(time.perf_counter() - start, 1)
        if self._packed_any or "pack" not in self.report.seconds:
            # A re-run that only rewrites the index keeps the real timing.
            self.report.seconds["pack"] = seconds
        self.report.stats["tiles"] = len(done)
        self.report.stats["bytes"] = sum(done.values())
        self._write_index({c: meta[c] | {"bytes": b} for c, b in done.items()}, out_dir)
        log.info(
            "stage pack: %d tiles, %.1f MiB, %.1f s",
            len(done),
            sum(done.values()) / 2**20,
            seconds,
        )

    def _process_tile(self, code: str, out_dir: Path) -> Path:
        tiles_dir = self.paths.tiles
        textured = tiles_dir / f"{code}_tex.glb"
        forced = self._forced("pack")
        if forced or not textured.exists():
            start = time.perf_counter()
            stem = f"tex_{code}"
            self._tool(
                f"texture_{code}",
                texture_cmd(self.tools, self.cfg, f"tiles/{code}.ply", f"{stem}.mvs"),
            )
            # Self-contained GLB: the atlas PNGs go into the binary chunk.
            d = self.paths.dense
            textured.write_bytes(embed_images((d / f"{stem}.glb").read_bytes(), d))
            for leftover in d.glob(f"{stem}*"):
                leftover.unlink()
            log.info("tile %s: textured in %.1f s", code, time.perf_counter() - start)
        world = tiles_dir / f"{code}_world.glb"
        if forced or not world.exists():
            data = transform_glb(
                textured.read_bytes(), self.to_three.apply, self.to_three.rotation
            )
            world.write_bytes(data)
        packed = out_dir / f"{code}.glb"
        if forced or not packed.exists():
            self._pack(code, out_dir)
        return packed

    def _pack(
        self, code: str, out_dir: Path, texture_limit_px: int | None = None
    ) -> None:
        start = time.perf_counter()
        self._packed_any = True
        self._tool(
            f"gltfpack_{code}",
            gltfpack_cmd(
                self.tools,
                (self.paths.tiles / f"{code}_world.glb").resolve(),
                (out_dir / f"{code}.glb").resolve(),
                texture_limit_px,
            ),
            timeout_s=HOUR_S,
        )
        log_text = (self.paths.logs / f"gltfpack_{code}.log").read_text("utf-8")
        if "Warning" in log_text or "Error" in log_text:
            raise ToolError(f"gltfpack reported problems for tile {code}:\n{log_text}")
        log.info("tile %s: packed in %.1f s", code, time.perf_counter() - start)

    def _write_index(self, done: Mapping[str, Any], out_dir: Path) -> None:
        entries = []
        for code, entry in sorted(done.items()):
            world = (self.paths.tiles / f"{code}_world.glb").read_bytes()
            stats = glb_stats(world)
            entries.append(
                {
                    "file": f"{out_dir.name}/{code}.glb",
                    "bytes": entry["bytes"],
                    "bounds": {
                        "min": [round(v, 3) for v in stats.bounds_min],
                        "max": [round(v, 3) for v in stats.bounds_max],
                    },
                    "triangles": stats.triangles,
                    "texture_px": [list(image_size(p)) for p in stats.images],
                    "quality": {
                        "coverage_share": entry["coverage_share"],
                        "hole_ratio": entry["hole_ratio"],
                        "untextured_share": _round(untextured_share(world)),
                    },
                }
            )
        update_index(
            self.paths.out_root / "index.json",
            {
                "run": self.cfg.run,
                "model": self.cfg.model,
                "georef_method": self.georef.get("method"),
                "georef_icp_rms_m": self.georef.get("quality", {}).get("icp_rms_m"),
                "resolution_level": self.cfg.resolution_level,
                "tiles": entries,
            },
        )


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", "utf-8")


# TextureMesh --empty-color default 16744231 = 0xFF7F27 (orange)
EMPTY_RGB = (0xFF, 0x7F, 0x27)


def untextured_share(
    glb: bytes, empty_rgb: tuple[int, int, int] = EMPTY_RGB, tol: int = 20
) -> float | None:
    """Area share of triangles whose texel at the UV centroid is the empty colour.

    Those faces were seen by no image (TextureMesh paints them orange; texel
    sharpening shifts the shade a little, hence the tolerance). The share is
    area-weighted: unseen faces are few but large (hole fillers).
    """
    from PIL import Image

    gltf, blob = read_glb(glb)
    images = glb_stats(glb).images
    if not images:
        return None
    textures = []
    for payload in images:
        with Image.open(io.BytesIO(payload)) as img:
            textures.append(np.asarray(img.convert("RGB")))
    empty = total = 0.0
    for mesh in gltf.get("meshes", []):
        for prim in mesh["primitives"]:
            if "TEXCOORD_0" not in prim["attributes"] or "indices" not in prim:
                continue
            uv = accessor_view(gltf, blob, prim["attributes"]["TEXCOORD_0"])
            idx = accessor_view(gltf, blob, prim["indices"]).astype(np.int64)
            tri = idx.reshape(-1, 3)
            cuv = uv.astype(np.float64)[tri].mean(axis=1)
            pos = accessor_view(gltf, blob, prim["attributes"]["POSITION"])
            corners = pos.astype(np.float64)[tri]
            area = 0.5 * np.linalg.norm(
                np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]),
                axis=1,
            )
            material = gltf["materials"][prim.get("material", 0)]
            texture = gltf["textures"][
                material["pbrMetallicRoughness"]["baseColorTexture"]["index"]
            ]
            tex = textures[texture["source"]]
            h, w = tex.shape[:2]
            px = np.clip((cuv[:, 0] * w).astype(np.int64), 0, w - 1)
            py = np.clip((cuv[:, 1] * h).astype(np.int64), 0, h - 1)
            diff = np.abs(tex[py, px].astype(np.int64) - np.array(empty_rgb))
            empty += float(area[np.all(diff <= tol, axis=1)].sum())
            total += float(area.sum())
    return empty / total if total else None


def image_size(payload: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(payload)) as img:
        return img.size


INDEX_FRAME = (
    "three.js world metres: x = east, y = up, z = -north; origin = campus ENU "
    "origin (amap_contracts.geo); y = 0 is the local ground under the cameras"
)


def update_index(path: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    """Insert or replace one run/model entry in ``data/out/mesh/index.json``."""
    index: dict[str, Any] = {"version": 1, "frame": INDEX_FRAME, "meshes": []}
    if path.is_file():
        index = json.loads(path.read_text("utf-8"))
    index["frame"] = INDEX_FRAME
    meshes = [
        m
        for m in index.get("meshes", [])
        if (m["run"], m["model"]) != (entry["run"], entry["model"])
    ]
    meshes.append(dict(entry))
    index["meshes"] = sorted(meshes, key=lambda m: (m["run"], m["model"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, index)
    return index
