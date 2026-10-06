"""Minimal binary PLY and GLB I/O with numpy (no mesh library dependency).

Only what the dense-mesh stage needs: OpenMVS writes little-endian binary PLY
(point clouds and triangle meshes) and glTF binary (``.glb``) textured meshes.
"""

import base64
import json
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

_PLY_TYPES: dict[str, str] = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "i2",
    "int16": "i2",
    "ushort": "u2",
    "uint16": "u2",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "uint32": "u4",
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
}


@dataclass(frozen=True, slots=True)
class _PlyProperty:
    name: str
    dtype: str  # numpy type code of the value (or of list items)
    count_dtype: str | None = None  # set for list properties


@dataclass(frozen=True, slots=True)
class _PlyElement:
    name: str
    count: int
    properties: tuple[_PlyProperty, ...]


def _parse_ply_header(data: bytes) -> tuple[list[_PlyElement], int]:
    end = data.find(b"end_header")
    if not data.startswith(b"ply") or end < 0:
        raise ValueError("not a PLY file")
    body_start = data.index(b"\n", end) + 1
    lines = data[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in lines:
        raise ValueError("only binary little-endian PLY is supported")
    elements: list[_PlyElement] = []
    name, count, props = "", 0, []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "element":
            if name:
                elements.append(_PlyElement(name, count, tuple(props)))
            name, count, props = parts[1], int(parts[2]), []
        elif parts[0] == "property":
            if parts[1] == "list":
                props.append(
                    _PlyProperty(parts[4], _PLY_TYPES[parts[3]], _PLY_TYPES[parts[2]])
                )
            else:
                props.append(_PlyProperty(parts[2], _PLY_TYPES[parts[1]]))
    if name:
        elements.append(_PlyElement(name, count, tuple(props)))
    return elements, body_start


def _fixed_list_lengths(
    data: bytes, offset: int, element: _PlyElement
) -> dict[str, int] | None:
    """Lengths of the list properties if they are equal on every row, else None."""
    lengths: dict[str, int] = {}
    pos = offset
    for prop in element.properties:
        if prop.count_dtype is None:
            pos += np.dtype(prop.dtype).itemsize
            continue
        n = int(np.frombuffer(data, prop.count_dtype, 1, pos)[0])
        lengths[prop.name] = n
        pos += np.dtype(prop.count_dtype).itemsize + n * np.dtype(prop.dtype).itemsize
    if not lengths or element.count == 0:
        return lengths
    fields: list[tuple[str, str] | tuple[str, str, tuple[int]]] = []
    for prop in element.properties:
        if prop.count_dtype is None:
            fields.append((prop.name, "<" + prop.dtype))
        else:
            fields.append((f"{prop.name}__n", "<" + prop.count_dtype))
            fields.append((prop.name, "<" + prop.dtype, (lengths[prop.name],)))
    dtype = np.dtype(fields)
    if offset + dtype.itemsize * element.count > len(data):
        return None
    rows = np.frombuffer(data, dtype, element.count, offset)
    for name, n in lengths.items():
        if not np.all(rows[f"{name}__n"] == n):
            return None
    return lengths


def _read_variable(
    data: bytes, offset: int, element: _PlyElement
) -> tuple[dict[str, NDArray[Any]], int]:
    """Rows with variable-length lists (e.g. OpenMVS per-point view lists).

    Returns the scalar properties that precede the first list property; the
    lists themselves are skipped.
    """
    steps: list[tuple[int, int, int]] = []  # (fixed bytes, count bytes, item bytes)
    for prop in element.properties:
        size = np.dtype(prop.dtype).itemsize
        if prop.count_dtype is None:
            steps.append((size, 0, 0))
        else:
            steps.append((0, np.dtype(prop.count_dtype).itemsize, size))
    starts = np.empty(element.count, np.int64)
    pos = offset
    for i in range(element.count):
        starts[i] = pos
        for fixed, count_bytes, item in steps:
            if count_bytes == 0:
                pos += fixed
            else:
                n = int.from_bytes(data[pos : pos + count_bytes], "little")
                pos += count_bytes + n * item
    raw = np.frombuffer(data, np.uint8)
    columns: dict[str, NDArray[Any]] = {}
    within = 0
    for prop in element.properties:
        if prop.count_dtype is not None:
            break
        dtype = np.dtype("<" + prop.dtype)
        idx = starts[:, None] + within + np.arange(dtype.itemsize)
        columns[prop.name] = raw[idx].copy().view(dtype).ravel()
        within += dtype.itemsize
    return columns, pos


def read_ply(path: Path) -> dict[str, dict[str, NDArray[Any]]]:
    """Read every element of a binary PLY as ``{element: {property: array}}``.

    Lists of the same length on every row (triangles) come back as (N, k)
    arrays; elements with variable-length lists only return the scalar
    properties before their first list.
    """
    data = path.read_bytes()
    elements, offset = _parse_ply_header(data)
    out: dict[str, dict[str, NDArray[Any]]] = {}
    for element in elements:
        lengths = _fixed_list_lengths(data, offset, element)
        if lengths is None:
            out[element.name], offset = _read_variable(data, offset, element)
            continue
        fields: list[tuple[str, str] | tuple[str, str, tuple[int]]] = []
        for prop in element.properties:
            if prop.count_dtype is None:
                fields.append((prop.name, "<" + prop.dtype))
            else:
                fields.append((f"{prop.name}__n", "<" + prop.count_dtype))
                fields.append((prop.name, "<" + prop.dtype, (lengths[prop.name],)))
        dtype = np.dtype(fields)
        rows = np.frombuffer(data, dtype, element.count, offset)
        offset += dtype.itemsize * element.count
        out[element.name] = {p.name: np.array(rows[p.name]) for p in element.properties}
    return out


def read_ply_mesh(path: Path) -> tuple[FloatArray, IntArray]:
    """Vertices (N, 3) and triangles (M, 3) of a PLY mesh."""
    ply = read_ply(path)
    vertex = ply["vertex"]
    vertices = np.stack([vertex["x"], vertex["y"], vertex["z"]], axis=1)
    face = ply.get("face", {})
    key = "vertex_indices" if "vertex_indices" in face else "vertex_index"
    faces = face[key] if face else np.zeros((0, 3), np.int64)
    if faces.shape[1:] != (3,):
        raise ValueError("only triangle meshes are supported")
    return vertices.astype(np.float64), faces.astype(np.int64)


def read_ply_points(path: Path) -> FloatArray:
    """XYZ (N, 3) of a PLY point cloud (or of a mesh's vertices)."""
    vertex = read_ply(path)["vertex"]
    return np.stack([vertex["x"], vertex["y"], vertex["z"]], axis=1).astype(np.float64)


def write_ply_mesh(path: Path, vertices: FloatArray, faces: IntArray) -> None:
    """Binary little-endian PLY with float xyz and uchar/int triangle lists."""
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(vertices)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        f"element face {len(faces)}\n"
        "property list uchar int vertex_indices\nend_header\n"
    )
    face_rows = np.zeros(len(faces), np.dtype([("n", "u1"), ("v", "<i4", (3,))]))
    face_rows["n"] = 3
    face_rows["v"] = faces
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(header.encode("ascii"))
        fh.write(np.ascontiguousarray(vertices, dtype="<f4").tobytes())
        fh.write(face_rows.tobytes())


# --- glTF binary ---------------------------------------------------------------

_GLB_MAGIC = 0x46546C67  # "glTF"
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942
_COMPONENTS: dict[int, str] = {
    5120: "i1",
    5121: "u1",
    5122: "<i2",
    5123: "<u2",
    5125: "<u4",
    5126: "<f4",
}
_TYPE_SIZE = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(
    data: bytes, base_dir: Path | None = None
) -> tuple[dict[str, Any], bytearray]:
    """Split a GLB into its JSON document and one (mutable) binary buffer.

    Extra buffers (OpenMVS writes the second texture's primitive into a
    base64 data URI) are appended to the binary chunk and their buffer views
    rebased, so every view afterwards points into buffer 0. File URIs are read
    relative to ``base_dir``.
    """
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC or version != 2:
        raise ValueError("not a glTF 2.0 binary")
    pos, gltf, blob = 12, None, bytearray()
    while pos < length:
        size, kind = struct.unpack_from("<II", data, pos)
        chunk = data[pos + 8 : pos + 8 + size]
        if kind == _CHUNK_JSON:
            gltf = json.loads(chunk.decode("utf-8"))
        elif kind == _CHUNK_BIN:
            blob = bytearray(chunk)
        pos += 8 + size
    if gltf is None:
        raise ValueError("GLB without a JSON chunk")
    _merge_buffers(gltf, blob, base_dir)
    return gltf, blob


def _buffer_payload(buffer: dict[str, Any], base_dir: Path | None) -> bytes:
    uri = str(buffer["uri"])
    if uri.startswith("data:"):
        return base64.b64decode(uri.split(",", 1)[1])
    if base_dir is None:
        raise ValueError(f"external glTF buffer {uri!r} needs a base directory")
    return (base_dir / uri).read_bytes()


def _merge_buffers(
    gltf: dict[str, Any], blob: bytearray, base_dir: Path | None
) -> None:
    buffers = gltf.get("buffers", [])
    if not buffers or (len(buffers) == 1 and "uri" not in buffers[0]):
        return
    offsets: dict[int, int] = {}
    for index, buffer in enumerate(buffers):
        if index == 0 and "uri" not in buffer:
            offsets[0] = 0
            continue
        blob.extend(b"\0" * (-len(blob) % 4))
        offsets[index] = len(blob)
        blob.extend(_buffer_payload(buffer, base_dir))
    for view in gltf.get("bufferViews", []):
        index = view.get("buffer", 0)
        view["buffer"] = 0
        view["byteOffset"] = view.get("byteOffset", 0) + offsets[index]
    gltf["buffers"] = [{"byteLength": len(blob)}]


def write_glb(gltf: dict[str, Any], blob: bytes | bytearray) -> bytes:
    if gltf.get("buffers"):
        gltf["buffers"][0]["byteLength"] = len(blob)
    text = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary = bytes(blob) + b"\0" * (-len(blob) % 4)
    chunks = struct.pack("<II", len(text), _CHUNK_JSON) + text
    if binary:
        chunks += struct.pack("<II", len(binary), _CHUNK_BIN) + binary
    return struct.pack("<III", _GLB_MAGIC, 2, 12 + len(chunks)) + chunks


def accessor_view(gltf: dict[str, Any], blob: bytearray, index: int) -> NDArray[Any]:
    """(count, k) numpy view into the binary chunk (writes go through)."""
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    if view.get("buffer", 0) != 0:
        raise ValueError("accessor outside the binary chunk (use read_glb)")
    dtype = np.dtype(_COMPONENTS[acc["componentType"]])
    k = _TYPE_SIZE[acc["type"]]
    stride = view.get("byteStride") or dtype.itemsize * k
    offset = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    return np.ndarray(
        (acc["count"], k),
        dtype,
        buffer=blob,
        offset=offset,
        strides=(stride, dtype.itemsize),
    )


def _attribute_accessors(gltf: dict[str, Any], name: str) -> list[int]:
    found = {
        prim["attributes"][name]
        for mesh in gltf.get("meshes", [])
        for prim in mesh["primitives"]
        if name in prim["attributes"]
    }
    return sorted(found)


def _check_identity_nodes(gltf: dict[str, Any]) -> None:
    for node in gltf.get("nodes", []):
        if any(k in node for k in ("matrix", "translation", "rotation", "scale")):
            raise ValueError("GLB nodes with transforms are not supported")


def transform_glb(
    data: bytes,
    points_fn: Callable[[FloatArray], FloatArray],
    rotation: FloatArray,
) -> bytes:
    """Bake a similarity into every POSITION (``points_fn``) and NORMAL accessor."""
    gltf, blob = read_glb(data)
    _check_identity_nodes(gltf)
    for index in _attribute_accessors(gltf, "POSITION"):
        view = accessor_view(gltf, blob, index)
        moved = points_fn(view.astype(np.float64))
        view[:] = moved.astype(view.dtype)
        acc = gltf["accessors"][index]
        acc["min"] = [float(v) for v in view.min(axis=0)]
        acc["max"] = [float(v) for v in view.max(axis=0)]
    for index in _attribute_accessors(gltf, "NORMAL"):
        view = accessor_view(gltf, blob, index)
        turned = view.astype(np.float64) @ rotation.T
        norm = np.linalg.norm(turned, axis=1, keepdims=True)
        view[:] = (turned / np.where(norm > 0, norm, 1.0)).astype(view.dtype)
    return write_glb(gltf, blob)


_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def embed_images(data: bytes, base_dir: Path) -> bytes:
    """Move images (and buffers) referenced by URIs into the binary chunk."""
    gltf, blob = read_glb(data, base_dir)
    views = gltf.setdefault("bufferViews", [])
    for image in gltf.get("images", []):
        uri = image.get("uri")
        if uri is None or uri.startswith("data:"):
            continue
        path = base_dir / uri
        payload = path.read_bytes()
        blob.extend(b"\0" * (-len(blob) % 4))
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(payload)})
        blob.extend(payload)
        del image["uri"]
        image["bufferView"] = len(views) - 1
        image["mimeType"] = _MIME[path.suffix.lower()]
    return write_glb(gltf, blob)


@dataclass(frozen=True, slots=True)
class GlbStats:
    triangles: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    images: tuple[bytes, ...]  # encoded image payloads (PNG/JPEG)


def glb_stats(data: bytes) -> GlbStats:
    gltf, blob = read_glb(data)
    triangles = 0
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for mesh in gltf.get("meshes", []):
        for prim in mesh["primitives"]:
            if "indices" in prim:
                triangles += gltf["accessors"][prim["indices"]]["count"] // 3
            else:
                triangles += (
                    gltf["accessors"][prim["attributes"]["POSITION"]]["count"] // 3
                )
    for index in _attribute_accessors(gltf, "POSITION"):
        pos = accessor_view(gltf, blob, index)
        if len(pos):
            lo = np.minimum(lo, pos.min(axis=0))
            hi = np.maximum(hi, pos.max(axis=0))
    images: list[bytes] = []
    for image in gltf.get("images", []):
        if "bufferView" in image:
            view = gltf["bufferViews"][image["bufferView"]]
            start = view.get("byteOffset", 0)
            images.append(bytes(blob[start : start + view["byteLength"]]))
    return GlbStats(
        triangles,
        (float(lo[0]), float(lo[1]), float(lo[2])),
        (float(hi[0]), float(hi[1]), float(hi[2])),
        tuple(images),
    )
