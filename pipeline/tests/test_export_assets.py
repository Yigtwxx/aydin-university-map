from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image
from shapely.geometry import Polygon

from amap_pipeline.acquire.store import FACES
from amap_pipeline.export.assets import (
    SMALL_FACE_PX,
    MassingParams,
    building_height_m,
    export_panos,
    greenery_json,
    massing,
)
from amap_pipeline.geo.osm import Building, Greenery


def _building(name: str | None, levels: float | None, dx: float = 0.0) -> Building:
    poly = Polygon([(dx, 10), (dx + 20, 10), (dx + 20, 30), (dx, 30)])
    return Building(osm_id=f"way/{dx}", name=name, levels=levels, outline=poly)


@pytest.mark.parametrize(("levels", "expected"), [(5.0, 16.0), (None, 9.6), (0.0, 9.6)])
def test_building_height_m_uses_levels_or_default(
    levels: float | None, expected: float
) -> None:
    result = building_height_m(_building(None, levels))
    assert result == pytest.approx(expected), f"Got {result}"


def test_massing_keeps_nearby_buildings_and_flags_campus() -> None:
    data = massing(
        [
            _building("İstanbul Aydın Üniversitesi A Binası", 4.0),
            _building("Far away", None, dx=5000.0),
        ],
        MassingParams(radius_m=450.0),
    )
    names = [b["name"] for b in data["buildings"]]
    assert names == ["İstanbul Aydın Üniversitesi A Binası"], f"Got {names}"
    assert data["buildings"][0]["campus"] is True
    assert data["buildings"][0]["height_source"] == "osm_levels"
    assert "OpenStreetMap" in data["attribution"]


def test_export_panos_writes_full_and_small_webp(
    tmp_path: Path, jpeg_factory: Callable[..., bytes]
) -> None:
    tiles = tmp_path / "tiles"
    for face in FACES:
        path = tiles / "scene_1" / f"{face}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(jpeg_factory(size=512))
    count = export_panos(["scene_1"], tiles, tmp_path / "panos")
    assert count == 2 * len(FACES), f"Got {count}"
    with Image.open(tmp_path / "panos" / "scene_1" / "f_s.webp") as small:
        assert small.size == (SMALL_FACE_PX, SMALL_FACE_PX), small.size


def test_greenery_json_keeps_nearby_areas_and_trees() -> None:
    near = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    far = Polygon([(9000, 0), (9010, 0), (9010, 10), (9000, 10)])
    data = greenery_json(
        Greenery([("grass", near), ("park", far)], [(1.0, 2.0), (8000.0, 0.0)])
    )
    assert [a["kind"] for a in data["areas"]] == ["grass"], data["areas"]
    assert data["trees"] == [[1.0, 2.0]], data["trees"]


def test_greenery_json_adds_surveyed_trees_once() -> None:
    data = greenery_json(
        Greenery([], [(1.0, 2.0)]), extra_trees=[(1.3, 2.2), (30.0, 40.0)]
    )
    # A surveyed tree within 1.5 m of an OSM one is the same tree.
    assert data["trees"] == [[1.0, 2.0], [30.0, 40.0]], data["trees"]
