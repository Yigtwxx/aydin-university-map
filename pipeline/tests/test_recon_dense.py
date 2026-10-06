import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from amap_pipeline.recon.dense import (
    EMPTY_RGB,
    ENU_TO_THREE,
    DenseConfig,
    Rect,
    ToolError,
    Tools,
    boundary_edges_per_face,
    camera_centre,
    coverage_share,
    crop_faces,
    crop_rect,
    densify_cmd,
    enu_to_three,
    filter_text_model,
    gltfpack_cmd,
    interface_cmd,
    large_components,
    model_to_enu,
    model_to_three,
    quadrant_index,
    quadtree,
    reconstruct_cmd,
    refine_cmd,
    run_logged,
    submesh,
    supported_faces,
    texture_cmd,
    three_to_enu,
    undistorter_cmd,
    untextured_share,
    update_index,
)
from amap_pipeline.recon.evaluate import horizontal_basis
from amap_pipeline.recon.meshio import (
    embed_images,
    glb_stats,
    read_glb,
    read_ply,
    read_ply_mesh,
    transform_glb,
    write_glb,
    write_ply_mesh,
)

TOOLS = Tools(openmvs_dir=Path("/opt/openmvs"), gltfpack=Path("/opt/gltfpack"))

# --- sparse model filtering ---------------------------------------------------

CAMERAS = """# Camera list
1 SIMPLE_PINHOLE 16 16 8 8 8
2 SIMPLE_PINHOLE 16 16 8 8 8
3 SIMPLE_PINHOLE 16 16 8 8 8
"""
# image 1 = f/a (cam 1), 2 = d/a (cam 2, nadir), 3 = r/b (cam 3)
IMAGES = """# Image list
1 1 0 0 0 0 0 0 1 f/a.jpg
1.0 2.0 10 3.0 4.0 11 5.0 6.0 -1
2 1 0 0 0 0 0 0 2 d/a.jpg
1.0 2.0 10 3.0 4.0 11
3 1 0 0 0 0 0 0 3 r/b.jpg
7.0 8.0 10
"""
# point 10 is seen by images 1, 2, 3; point 11 only by 1 and the nadir image 2
POINTS = """# 3D point list
10 0.1 0.2 0.3 1 2 3 0.5 1 0 2 0 3 0
11 0.4 0.5 0.6 4 5 6 0.7 1 1 2 1
"""


def test_filter_text_model_drops_nadir_images_and_orphan_points() -> None:
    out = filter_text_model(CAMERAS, IMAGES, POINTS, ("d",))
    assert (out.kept_images, out.dropped_images) == (2, 1)
    assert (out.kept_points, out.dropped_points) == (1, 1)
    image_lines = out.images.splitlines()
    assert [line.split()[-1] for line in image_lines[::2]] == ["f/a.jpg", "r/b.jpg"]
    # point 11 lost its second view: its 2D reference is reset
    assert image_lines[1] == "1.0 2.0 10 3.0 4.0 -1 5.0 6.0 -1"
    assert out.points3d.strip() == "10 0.1 0.2 0.3 1 2 3 0.5 1 0 3 0"
    assert [line.split()[0] for line in out.cameras.splitlines()] == ["1", "3"]


def test_filter_text_model_drops_faces_without_enough_points() -> None:
    # r/b (image 3) observes one point only
    out = filter_text_model(CAMERAS, IMAGES, POINTS, ("d",), min_observations=2)
    assert out.kept_images == 1
    assert [line.split()[-1] for line in out.images.splitlines()[::2]] == ["f/a.jpg"]
    assert out.kept_points == 0  # every track fell below two views


def test_filter_text_model_drops_points_at_acamera_centre() -> None:
    # every camera sits at the origin (identity pose); point 10 is 0.37 away
    out = filter_text_model(CAMERAS, IMAGES, POINTS, (), min_point_distance=0.5)
    assert out.kept_points == 1
    assert out.points3d.split()[0] == "11"


def testcamera_centre_inverts_the_pose() -> None:
    # 90 deg about z (w = cos 45, z = sin 45), t = (1, 0, 0): C = -R^T t
    h = math.sqrt(0.5)
    header = ["1", str(h), "0", "0", str(h), "1", "0", "0", "1", "f/a.jpg"]
    np.testing.assert_allclose(camera_centre(header), [0.0, 1.0, 0.0], atol=1e-12)


def test_filter_text_model_without_exclusions_keeps_everything() -> None:
    out = filter_text_model(CAMERAS, IMAGES, POINTS, ())
    assert (out.kept_images, out.dropped_points) == (3, 0)


# --- command lines ------------------------------------------------------------


def test_densify_command_disables_object_roi_and_tower_mode() -> None:
    cmd = densify_cmd(TOOLS, DenseConfig(run="r", model=0, resolution_level=2))
    assert cmd[0] == "/opt/openmvs/DensifyPointCloud"
    assert cmd[1] == "scene.mvs"
    pairs = dict(zip(cmd[2::2], cmd[3::2], strict=True))
    assert pairs["--resolution-level"] == "2"
    assert pairs["--max-threads"] == "0"
    assert pairs["--estimate-roi"] == "0"
    assert pairs["--crop-to-roi"] == "0"
    assert pairs["--tower-mode"] == "0"
    assert pairs["-o"] == "scene_dense.mvs"


def test_mesh_commands_chain_dense_outputs() -> None:
    cfg = DenseConfig(run="r", model=0, refine_resolution_level=3, max_texture_px=4096)
    mesh = reconstruct_cmd(TOOLS, cfg)
    assert mesh[:4] == [
        "/opt/openmvs/ReconstructMesh",
        "scene_dense.mvs",
        "-p",
        "scene_dense.ply",
    ]
    refine = refine_cmd(TOOLS, cfg)
    assert refine[refine.index("-m") + 1] == "scene_mesh_clean.ply"
    assert refine[refine.index("--resolution-level") + 1] == "3"
    texture = texture_cmd(TOOLS, cfg, "tiles/r0.ply", "tex_r0.mvs")
    assert texture[texture.index("--export-type") + 1] == "glb"
    assert texture[texture.index("-m") + 1] == "tiles/r0.ply"
    assert texture[texture.index("--max-texture-size") + 1] == "4096"
    assert texture[texture.index("--close-holes") + 1] == "0"
    assert texture[texture.index("--global-seam-leveling") + 1] == "0"
    assert texture[texture.index("--local-seam-leveling") + 1] == "0"
    assert texture[1] == "scene.mvs"  # full-size images, not the densify copy
    with pytest.raises(ValueError, match="bare file name"):
        texture_cmd(TOOLS, cfg, "tiles/r0.ply", "tiles/tex_r0.mvs")
    interface = interface_cmd(TOOLS)
    assert interface[interface.index("--image-folder") + 1] == "images"


def test_colmap_and_gltfpack_commands() -> None:
    und = undistorter_cmd("colmap", Path("/i"), Path("/s"), Path("/o"))
    assert und[:2] == ["colmap", "image_undistorter"]
    assert und[und.index("--output_type") + 1] == "COLMAP"
    pack = gltfpack_cmd(TOOLS, Path("a.glb"), Path("b.glb"))
    assert pack == ["/opt/gltfpack", "-i", "a.glb", "-o", "b.glb", "-cc", "-tc"]
    assert gltfpack_cmd(TOOLS, Path("a"), Path("b"), 2048)[-2:] == ["-tl", "2048"]


def test_run_logged_writes_log_and_raises_on_failure(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "ok.log"
    run_logged([sys.executable, "-c", "print('hello')"], log, timeout_s=30)
    assert "hello" in log.read_text("utf-8")
    with pytest.raises(ToolError, match="exited with 3"):
        run_logged([sys.executable, "-c", "raise SystemExit(3)"], log, timeout_s=30)
    with pytest.raises(ToolError, match="timed out"):
        run_logged(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            log,
            timeout_s=0.2,
            poll_s=0.05,
        )


def test_run_logged_kills_a_silent_idle_tool(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="stalled"):
        run_logged(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            tmp_path / "idle.log",
            timeout_s=30,
            stall_s=0.3,
            poll_s=0.05,
        )


# --- georeference and frames --------------------------------------------------


def _georef(yaw_deg: float = 30.0, scale: float = 2.5) -> dict[str, Any]:
    down = np.array([0.1, 0.95, -0.2])
    down /= np.linalg.norm(down)
    e1, e2 = horizontal_basis(down)
    return {
        "basis_levelled_from_model": [e1.tolist(), e2.tolist(), (-down).tolist()],
        "similarity": {
            "yaw_deg": yaw_deg,
            "scale_m_per_unit": scale,
            "shift_m": [10.0, -4.0],
        },
        "ground_z_model": -0.4,
    }


def test_model_to_enu_matches_the_georef_formula() -> None:
    doc = _georef()
    sim = model_to_enu(doc)
    p = np.array([[1.0, -2.0, 3.0], [0.5, 0.0, -1.0]])
    basis = np.array(doc["basis_levelled_from_model"])
    lev = p @ basis.T
    yaw = math.radians(30.0)
    rot = np.array([[math.cos(yaw), -math.sin(yaw)], [math.sin(yaw), math.cos(yaw)]])
    xy = 2.5 * lev[:, :2] @ rot.T + [10.0, -4.0]
    z = 2.5 * (lev[:, 2] + 0.4)
    np.testing.assert_allclose(sim.apply(p), np.column_stack([xy, z]), atol=1e-12)
    assert sim.scale == pytest.approx(2.5)
    np.testing.assert_allclose(sim.rotation @ sim.rotation.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(sim.rotation) == pytest.approx(1.0)


def test_enu_to_three_axis_mapping() -> None:
    # Same mapping as enuToWorld in the web app: (e, n, u) -> (e, u, -n).
    np.testing.assert_allclose(enu_to_three(np.array([[3.0, 5.0, 2.0]])), [[3, 2, -5]])
    pts = np.random.default_rng(1).normal(size=(5, 3))
    np.testing.assert_allclose(three_to_enu(enu_to_three(pts)), pts)
    assert np.linalg.det(ENU_TO_THREE) == pytest.approx(1.0)  # no mirror


def test_model_to_three_composes_enu_then_axes() -> None:
    doc = _georef()
    p = np.array([[0.2, 0.3, -0.7]])
    np.testing.assert_allclose(
        model_to_three(doc).apply(p), enu_to_three(model_to_enu(doc).apply(p))
    )


# --- crop, tiles and quality --------------------------------------------------


def test_crop_faces_uses_camera_bbox_margin_and_height() -> None:
    cams = np.array([[0.0, 0.0], [10.0, 20.0]])
    cent = np.array(
        [
            [5.0, 5.0, 2.0],  # inside
            [-29.0, 49.0, 0.0],  # inside the 30 m margin
            [-31.0, 5.0, 0.0],  # west of the margin
            [5.0, 5.0, 120.0],  # too high (sky noise)
        ]
    )
    keep = crop_faces(cent, cams, 30.0, (-15.0, 100.0))
    assert keep.tolist() == [True, True, False, False]
    root = crop_rect(cams, 30.0)
    assert root.x1 - root.x0 == pytest.approx(root.y1 - root.y0) == pytest.approx(80)


def test_quadrant_index_is_a_strict_partition() -> None:
    rect = Rect(0.0, 0.0, 10.0, 10.0)
    pts = np.array([[1.0, 1.0], [6.0, 1.0], [1.0, 6.0], [6.0, 6.0], [5.0, 5.0]])
    assert quadrant_index(pts, rect).tolist() == [0, 1, 2, 3, 3]


def test_quadtree_splits_dense_areas_and_keeps_every_face_once() -> None:
    rng = np.random.default_rng(0)
    dense = rng.uniform(0, 10, size=(900, 2))  # crowded south-west corner
    sparse = rng.uniform(0, 100, size=(100, 2))
    cent = np.concatenate([dense, sparse])
    tiles = quadtree(cent, Rect(0, 0, 100, 100), max_faces=200, min_size_m=4.0)
    together = np.sort(np.concatenate([t.faces for t in tiles]))
    np.testing.assert_array_equal(together, np.arange(len(cent)))
    assert all(len(t.faces) <= 200 or t.rect.size / 2 < 4.0 for t in tiles)
    assert {t.code[:2] for t in tiles} >= {"r0"}
    assert any(len(t.code) > 3 for t in tiles)  # the crowded corner went deeper
    for t in tiles:
        inside = (
            (cent[t.faces, 0] >= t.rect.x0)
            & (cent[t.faces, 0] <= t.rect.x1)
            & (cent[t.faces, 1] >= t.rect.y0)
            & (cent[t.faces, 1] <= t.rect.y1)
        )
        assert inside.all()


def test_quadtree_stops_at_min_size() -> None:
    cent = np.full((50, 2), 1.0)
    tiles = quadtree(cent, Rect(0, 0, 16, 16), max_faces=10, min_size_m=4.0)
    assert len(tiles) == 1 and tiles[0].rect.size == pytest.approx(4.0)


def test_submesh_reindexes_vertices() -> None:
    verts = np.arange(15, dtype=np.float64).reshape(5, 3)
    faces = np.array([[0, 1, 2], [2, 3, 4]])
    v, f = submesh(verts, faces, np.array([1]))
    np.testing.assert_array_equal(v, verts[[2, 3, 4]])
    np.testing.assert_array_equal(f, [[0, 1, 2]])


def test_supported_faces_drop_surfaces_far_from_the_cloud() -> None:
    verts = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [10, 0, 0], [11, 0, 0], [10, 1, 0]],
        dtype=np.float64,
    )
    faces = np.array([[0, 1, 2], [3, 4, 5]])
    cloud = np.array([[0.3, 0.3, 0.1]])
    assert supported_faces(verts, faces, cloud, 0.5).tolist() == [True, False]


def test_large_components_drop_small_islands() -> None:
    strip = np.array([[i, i + 1, i + 2] for i in range(6)])  # 6 connected faces
    island = np.array([[20, 21, 22]])
    keep = large_components(np.concatenate([strip, island]), min_faces=3)
    assert keep.tolist() == [True] * 6 + [False]


def test_boundary_edges_open_quad_and_closed_tetrahedron() -> None:
    quad = np.array([[0, 1, 2], [0, 2, 3]])
    assert boundary_edges_per_face(quad).tolist() == [2, 2]
    tetra = np.array([[0, 1, 2], [0, 3, 1], [1, 3, 2], [2, 3, 0]])
    assert boundary_edges_per_face(tetra).tolist() == [0, 0, 0, 0]


def test_coverage_share_counts_occupied_cells() -> None:
    xs, ys = np.meshgrid(np.arange(0.5, 10, 1.0), np.arange(0.5, 5, 1.0))
    pts = np.column_stack([xs.ravel(), ys.ravel()])  # southern half of 10 x 10
    assert coverage_share(pts, Rect(0, 0, 10, 10), 1.0) == pytest.approx(0.5)


def test_coverage_share_near_cameras_only_counts_visible_surroundings() -> None:
    xs, ys = np.meshgrid(np.arange(0.5, 10, 1.0), np.arange(0.5, 5, 1.0))
    pts = np.column_stack([xs.ravel(), ys.ravel()])
    rect = Rect(0, 0, 10, 10)
    south = coverage_share(pts, rect, 1.0, np.array([[5.0, 1.0]]), radius_m=2.0)
    assert south == pytest.approx(1.0)
    north = coverage_share(pts, rect, 1.0, np.array([[5.0, 9.0]]), radius_m=2.0)
    assert north == pytest.approx(0.0)
    assert coverage_share(pts, rect, 1.0, np.array([[50.0, 50.0]])) is None


def test_update_index_replaces_the_same_model(tmp_path: Path) -> None:
    path = tmp_path / "mesh" / "index.json"
    update_index(path, {"run": "a", "model": 0, "tiles": [1]})
    update_index(path, {"run": "a", "model": 1, "tiles": [2]})
    index = update_index(path, {"run": "a", "model": 0, "tiles": [3]})
    assert [(m["model"], m["tiles"]) for m in index["meshes"]] == [(0, [3]), (1, [2])]
    assert "z = -north" in json.loads(path.read_text("utf-8"))["frame"]


# --- PLY / GLB I/O ------------------------------------------------------------


def test_ply_mesh_roundtrip(tmp_path: Path) -> None:
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
    faces = np.array([[0, 1, 2], [0, 1, 3]])
    write_ply_mesh(tmp_path / "m.ply", verts, faces)
    v, f = read_ply_mesh(tmp_path / "m.ply")
    np.testing.assert_allclose(v, verts)
    np.testing.assert_array_equal(f, faces)


def test_read_ply_point_cloud_with_colours_and_view_lists(tmp_path: Path) -> None:
    header = (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 2\n"
        b"property float x\nproperty float y\nproperty float z\n"
        b"property uchar red\nproperty list uchar uint views\nend_header\n"
    )
    rows = b"".join(
        struct.pack("<fffBBII", x, x + 1, x + 2, 200, 2, 7, 9) for x in (1.0, 4.0)
    )
    (tmp_path / "p.ply").write_bytes(header + rows)
    vertex = read_ply(tmp_path / "p.ply")["vertex"]
    np.testing.assert_allclose(vertex["z"], [3.0, 6.0])
    assert vertex["red"].tolist() == [200, 200]
    assert vertex["views"].tolist() == [[7, 9], [7, 9]]


def _triangle_glb(node: dict[str, Any] | None = None) -> bytes:
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4")
    nrm = np.array([[0, 0, 1]] * 3, dtype="<f4")
    idx = np.array([0, 1, 2], dtype="<u2")
    blob = pos.tobytes() + nrm.tobytes() + idx.tobytes()
    gltf = {
        "asset": {"version": "2.0"},
        "scenes": [{"nodes": [0]}],
        "nodes": [node or {"mesh": 0}],
        "meshes": [
            {"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2}]}
        ],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 36},
            {"buffer": 0, "byteOffset": 72, "byteLength": 6},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    return write_glb(gltf, blob)


def test_transform_glb_bakes_the_similarity_into_positions_and_normals() -> None:
    doc = _georef(yaw_deg=90.0, scale=2.0)
    sim = model_to_three(doc)
    moved = transform_glb(_triangle_glb(), sim.apply, sim.rotation)
    gltf, blob = read_glb(moved)
    pos = np.frombuffer(bytes(blob[:36]), "<f4").reshape(3, 3)
    expected = sim.apply(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float64))
    np.testing.assert_allclose(pos, expected, atol=1e-5)
    np.testing.assert_allclose(
        gltf["accessors"][0]["min"], expected.min(axis=0), atol=1e-5
    )
    nrm = np.frombuffer(bytes(blob[36:72]), "<f4").reshape(3, 3)
    np.testing.assert_allclose(nrm[0], sim.rotation @ [0, 0, 1], atol=1e-6)
    stats = glb_stats(moved)
    assert stats.triangles == 1
    np.testing.assert_allclose(stats.bounds_max, expected.max(axis=0), atol=1e-5)


def test_embed_images_moves_external_textures_into_the_binary_chunk(
    tmp_path: Path,
) -> None:
    png = b"\x89PNG\r\n\x1a\nfake"
    (tmp_path / "atlas_0.png").write_bytes(png)
    gltf, blob = read_glb(_triangle_glb())
    gltf["images"] = [{"uri": "atlas_0.png"}]
    data = embed_images(write_glb(gltf, blob), tmp_path)
    out, out_blob = read_glb(data)
    image = out["images"][0]
    assert "uri" not in image and image["mimeType"] == "image/png"
    view = out["bufferViews"][image["bufferView"]]
    start = view["byteOffset"]
    assert bytes(out_blob[start : start + view["byteLength"]]) == png
    assert glb_stats(data).images == (png,)


def test_untextured_share_counts_faces_on_the_empty_colour() -> None:
    import io

    from PIL import Image

    # 2x1 texture: left texel orange (no view), right texel grey
    tex = Image.new("RGB", (2, 1), (128, 128, 128))
    tex.putpixel((0, 0), EMPTY_RGB)
    buf = io.BytesIO()
    tex.save(buf, format="PNG")
    # triangle 1 (unseen) has area 2, triangle 2 has area 0.5 -> 0.8
    pos = np.array(
        [[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 0], [1, 0, 0], [0, 1, 0]],
        dtype="<f4",
    )
    uv = np.array([[0.2, 0.5]] * 3 + [[0.8, 0.5]] * 3, dtype="<f4")
    idx = np.arange(6, dtype="<u2")
    png = buf.getvalue()
    blob = pos.tobytes() + uv.tobytes() + idx.tobytes() + png
    gltf = {
        "asset": {"version": "2.0"},
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                        "indices": 2,
                        "material": 0,
                    }
                ]
            }
        ],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
        "textures": [{"source": 0}],
        "images": [{"bufferView": 3, "mimeType": "image/png"}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 72},
            {"buffer": 0, "byteOffset": 72, "byteLength": 48},
            {"buffer": 0, "byteOffset": 120, "byteLength": 12},
            {"buffer": 0, "byteOffset": 132, "byteLength": len(png)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 6, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 6, "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": 6, "type": "SCALAR"},
        ],
    }
    assert untextured_share(write_glb(gltf, blob)) == pytest.approx(0.8)


def test_transform_glb_handles_a_second_buffer_in_a_data_uri() -> None:
    import base64

    gltf, blob = read_glb(_triangle_glb())
    extra = np.array([[2, 0, 0], [3, 0, 0], [2, 1, 0]], dtype="<f4").tobytes()
    gltf["buffers"].append(
        {
            "byteLength": len(extra),
            "uri": "data:application/octet-stream;base64,"
            + base64.b64encode(extra).decode(),
        }
    )
    gltf["bufferViews"].append({"buffer": 1, "byteLength": len(extra)})
    gltf["accessors"].append(
        {"bufferView": 3, "componentType": 5126, "count": 3, "type": "VEC3"}
    )
    gltf["meshes"][0]["primitives"].append({"attributes": {"POSITION": 3}})
    moved = transform_glb(write_glb(gltf, blob), lambda p: p + 10.0, np.eye(3))
    out, out_blob = read_glb(moved)
    assert len(out["buffers"]) == 1
    first = np.frombuffer(bytes(out_blob[:36]), "<f4").reshape(3, 3)
    np.testing.assert_allclose(first[1], [11.0, 10.0, 10.0])
    view = out["bufferViews"][3]
    start = view["byteOffset"]
    second = np.frombuffer(bytes(out_blob[start : start + 36]), "<f4").reshape(3, 3)
    np.testing.assert_allclose(second[0], [12.0, 10.0, 10.0])


def test_transform_glb_refuses_node_transforms() -> None:
    data = _triangle_glb({"mesh": 0, "translation": [1, 0, 0]})
    with pytest.raises(ValueError, match="node"):
        transform_glb(data, lambda p: p, np.eye(3))
