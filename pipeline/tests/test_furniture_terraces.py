"""The campus terrace's grassy bank against the real building footprints.

The renderer draws a 'slope' terrace's bank as a band from the outline out to
its mitred offset (``offsetRing`` in apps/web/.../furnitureGeometry.ts). No
building may stand on that band or across the outline itself.
"""

import json
import math
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import Polygon
from shapely.validation import make_valid

from amap_pipeline.export.furniture import build_furniture, read_furniture
from amap_pipeline.paths import data_dir

# terrain.ts: a bank runs 1.8 m per metre climbed, 0.6-8 m, unless given.
_RUN_PER_M = 1.8
_BANK_MIN_M = 0.6
_BANK_MAX_M = 8.0
_MITRE_MIN_COS = 0.4
_TOLERANCE_M2 = 0.01

type XY = tuple[float, float]


def _ccw(ring: list[XY]) -> list[XY]:
    if ring[0] == ring[-1]:
        ring = ring[:-1]
    doubled = sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(ring, ring[1:] + ring[:1], strict=True)
    )
    return ring if doubled > 0 else ring[::-1]


def _offset_ring(ring: list[XY], d: float) -> list[XY]:
    """Mirror of furnitureGeometry.ts offsetRing: outward for a CCW ring."""

    def outward(a: XY, b: XY) -> XY:
        length = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        return ((b[1] - a[1]) / length, -(b[0] - a[0]) / length)

    out: list[XY] = []
    for i, p in enumerate(ring):
        n1 = outward(ring[i - 1], p)
        n2 = outward(p, ring[(i + 1) % len(ring)])
        mx, my = n1[0] + n2[0], n1[1] + n2[1]
        length = math.hypot(mx, my)
        if length < 1e-6:
            out.append((p[0] + n1[0] * d, p[1] + n1[1] * d))
            continue
        ux, uy = mx / length, my / length
        scale = 1 / max(ux * n1[0] + uy * n1[1], _MITRE_MIN_COS)
        out.append((p[0] + ux * d * scale, p[1] + uy * d * scale))
    return out


def _bank_quads(ring: list[XY], bank: float) -> list[Polygon]:
    outer = _offset_ring(ring, bank)
    n = len(ring)
    return [
        Polygon([ring[i], ring[(i + 1) % n], outer[(i + 1) % n], outer[i]])
        for i in range(n)
    ]


def _bank_width(z_m: float, around: float, bank_m: float | None) -> float:
    if bank_m is not None:
        return bank_m
    return min(_BANK_MAX_M, max(_BANK_MIN_M, abs(z_m - around) * _RUN_PER_M))


def test_bank_quads_follow_a_concave_ring_without_overlap() -> None:
    # An L: the reflex corner's mitre must not fold the bank over itself.
    ring = _ccw([(0, 0), (20, 0), (20, 8), (8, 8), (8, 20), (0, 20)])
    quads = _bank_quads(ring, 3.0)
    core = Polygon(ring)
    assert all(q.is_valid and q.area > 0 for q in quads), "a bank quad folded"
    assert all(q.intersection(core).area < 1e-9 for q in quads), "bank on the top"
    for i, a in enumerate(quads):
        for b in quads[i + 1 :]:
            assert a.intersection(b).area < 1e-9, "bank quads overlap"


@pytest.fixture(scope="module")
def buildings() -> list[dict[str, Any]]:
    path = Path(data_dir()) / "out" / "buildings.json"
    if not path.is_file():
        pytest.skip(f"{path} not built (uv run amap export buildings)")
    return json.loads(path.read_text("utf-8"))["buildings"]


def test_campus_bank_clears_every_building(buildings: list[dict[str, Any]]) -> None:
    furniture = build_furniture(read_furniture())
    campus = next(t for t in furniture.terraces if t.id == "campus")
    ring = _ccw([(float(x), float(y)) for x, y in campus.outline])
    core = Polygon(ring)
    assert core.is_valid, "the campus outline crosses itself"
    quads = _bank_quads(ring, _bank_width(campus.z_m, 0.0, campus.bank_m))

    on_bank: list[str] = []
    across: list[str] = []
    for building in buildings:
        footprint = make_valid(Polygon(building["outline"]))
        if footprint.distance(core) > _BANK_MAX_M * 3:
            continue
        if any(q.intersection(footprint).area > _TOLERANCE_M2 for q in quads):
            on_bank.append(building["id"])
        inside = footprint.intersection(core).area
        if _TOLERANCE_M2 < inside < footprint.area - _TOLERANCE_M2:
            across.append(building["id"])
    assert on_bank == [], f"buildings on the campus bank: {on_bank}"
    assert across == [], f"buildings across the campus outline: {across}"
