"""Synthetic krpano dump fixtures (no real tour data is ever used in tests)."""

import json
from pathlib import Path

import pytest

from amap_pipeline.tour import Scene, parse_scene

FLORYA = (40.991470, 28.797111)
OTHER_CAMPUS = (41.020931, 28.583117)

# name -> (label_tr, coords or None, linked scene names)
_SYNTHETIC: dict[str, tuple[str, tuple[float, float] | None, list[str]]] = {
    "scene_900001": ("Kampüs", FLORYA, ["scene_900002", "scene_900003"]),
    "scene_900002": ("Kampüs", FLORYA, ["scene_900001", "scene_900004"]),
    "scene_900003": ("Kampüs", FLORYA, ["scene_900001", "scene_900006"]),
    "scene_900004": ("Otopark", FLORYA, ["scene_900002", "scene_900005"]),
    "scene_900005": ("T Blok Bahçe", FLORYA, ["scene_900004"]),
    "scene_900006": ("A Blok Girişi", FLORYA, ["scene_900003", "scene_900007"]),
    "scene_900007": ("A Blok 1.Kat", FLORYA, ["scene_900006", "scene_900008"]),
    "scene_900008": ("Kafe - Giriş Kat", FLORYA, ["scene_900007"]),
    "scene_900009": ("Kampüs", OTHER_CAMPUS, ["scene_900001"]),
    "scene_900010": ("", None, ["scene_900001"]),
    "scene_900011": ("Kampüs", FLORYA, ["scene_999999"]),  # isolated, dangling
    "scene_900012": ("KÜTÜPHANE GİRİŞ", FLORYA, []),
}


def _onstart(scene_id: str, label: str, coords: tuple[float, float] | None) -> str:
    if coords is None:
        return f"mekanibelirle(901); sceneacildi({scene_id},get(panorama),get(onceki));"
    zeros6 = ",".join(["0"] * 6)
    params = [
        scene_id,
        "0",
        zeros6,
        zeros6,
        zeros6,
        zeros6,
        f"{coords[0]:.6f}",
        f"{coords[1]:.6f}",
        "355",
        "501",
        "501",
        label,
        "Florya Kampüs",
        "Florya Campus",
        "Campus",
    ]
    return f"hedefibelirle({','.join(params)});"


def synthetic_rows() -> list[list[object]]:
    rows: list[list[object]] = []
    for index, (name, (label, coords, links)) in enumerate(_SYNTHETIC.items()):
        scene_id = name.removeprefix("scene_")
        hotspots = [
            [
                f"spot{i}",
                target,
                str(90 * i),
                "0",
                str(45 * i),
                "skin_hotspotstyle_navigate",
            ]
            for i, target in enumerate(links)
        ]
        rows.append([index, name, label, _onstart(scene_id, label, coords), hotspots])
    return rows


@pytest.fixture
def scenes() -> list[Scene]:
    return [parse_scene(row) for row in synthetic_rows()]


@pytest.fixture
def dump_path(tmp_path: Path) -> Path:
    path = tmp_path / "raw" / "tour_scenes.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(synthetic_rows(), ensure_ascii=False), encoding="utf-8")
    return path
