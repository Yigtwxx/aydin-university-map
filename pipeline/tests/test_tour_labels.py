from typing import Any

import pytest

from amap_pipeline.tour.labels import (
    FloorReading,
    block_of,
    floor_of,
    read_floor,
    resolve_floors,
)


@pytest.mark.parametrize(
    ("label", "area", "expected"),
    [
        # Plain numbers and ground floors are certain.
        ("T Blok 2.Kat", "T Blok", FloorReading(2)),
        ("D Blok 1. Kat", "D Blok", FloorReading(1)),
        ("Kütüphane 0.Kat", "Kütüphane", FloorReading(0)),
        ("Egzersiz Odası - 1", "FTR - M Blok 2.K", FloorReading(2)),
        ("D Blok Giriş Kat", "D Blok", FloorReading(0)),
        ("Giriş Kat - Kafeterya", "Kütüphane", FloorReading(0)),
        # Bodrum or B is a basement, and makes the area's hyphen a minus.
        ("2. Bod.Kat Koridor", "E Blok", FloorReading(-2)),
        ("M Blok-3.Bodrum", "M Blok", FloorReading(-3)),
        ("Laboratuar", "M Blok-3.Bodrum", FloorReading(-3)),
        ("Bodrum Koridor", "M Blok-3.K", FloorReading(-3)),
        ("Depo", "2.B", FloorReading(-2)),
        # A hyphen right before the digit is a basement by default.
        ("T Blok -2.Kat", "T Blok", FloorReading(-2, "spaced")),
        ("Kütüphane -1.Kat", "Kütüphane", FloorReading(-1, "spaced")),
        ("-3. Kat", "", FloorReading(-3, "spaced")),
        ("M Blok -5 Koridor", "M Blok-5.K", FloorReading(-5, "spaced")),
        ("D Blok -1 Koridor", "D Blok", FloorReading(-1, "spaced")),
        # A hyphen glued to a word is in doubt (upper floor until settled).
        ("Laboratuar", "M Blok-3.K", FloorReading(3, "glued")),
        ("Derslik", "Gastronomi - O Blok-1.K", FloorReading(1, "glued")),
        # ... unless the area names the same floor plainly.
        ("M Blok-1.Kat Koridor", "M Blok 1.K", FloorReading(1)),
        # Room numbers and relative floors are no floors.
        ("Simultane Çeviri Odası - 2", "E Blok", None),
        ("Hasta Odaları - Normal Kat", "Tıp Fakültesi Hastanesi", None),
        ("Anatomi Lab", "Sağlık Bilimleri", None),
    ],
)
def test_read_floor_tells_basements_and_doubtful_hyphens(
    label: str, area: str, expected: FloorReading | None
) -> None:
    assert read_floor(label, area) == expected, f"{label!r} / {area!r}"


def test_floor_of_without_the_tour_keeps_the_defaults() -> None:
    assert floor_of("M Blok -5 Koridor", "M Blok-5.K") == -5
    assert floor_of("Laboratuar", "M Blok-4.K") == 4


def _scenes(spec: dict[str, tuple[str, str, list[str]]]) -> dict[str, Any]:
    links: dict[str, set[str]] = {
        name: set(linked) for name, (*_, linked) in spec.items()
    }
    for name, (*_, linked) in spec.items():
        for other in linked:
            links[other].add(name)
    return {
        name: {
            "label": {"tr": label, "en": label},
            "area": {"tr": area, "en": area},
            "links": sorted(links[name]),
        }
        for name, (label, area, _) in spec.items()
    }


def test_resolve_floors_m_blok_corridor_and_classroom_agree() -> None:
    # The spaced "-5" is a basement; the glued "M Blok-5.K" follows it.
    scenes = _scenes(
        {
            "corridor": ("M Blok -5 Koridor", "M Blok-5.K", ["class"]),
            "class": ("Hemşirelik Sınıfı", "M Blok-5.K", []),
        }
    )
    notes: dict[str, str] = {}
    floors = resolve_floors(scenes, notes)
    assert floors == {"corridor": -5, "class": -5}, f"Got {floors}"
    assert notes["class"].startswith("follows"), notes


def test_resolve_floors_a_flip_removes_a_big_jump() -> None:
    # T Blok 3.Kat links Kütüphane -3.Kat: -3 would jump six floors, +3 none.
    scenes = _scenes(
        {
            "t3": ("T Blok 3.Kat", "T Blok", ["k3"]),
            "k3": ("Kütüphane -3.Kat", "Kütüphane", []),
        }
    )
    notes: dict[str, str] = {}
    assert resolve_floors(scenes, notes) == {"t3": 3, "k3": 3}
    assert notes["k3"].startswith("upper floor"), notes


def test_resolve_floors_plain_floor_in_the_building_keeps_the_basement() -> None:
    # The library writes 3.Kat plainly elsewhere: -3.Kat is its basement,
    # even next to T Blok's third floor (the jump is reported, not hidden).
    scenes = _scenes(
        {
            "t3": ("T Blok 3.Kat", "T Blok", ["k3"]),
            "k3": ("Kütüphane -3.Kat", "Kütüphane", []),
            "up3": ("Kütüphane 3.Kat", "Kütüphane", []),
        }
    )
    assert resolve_floors(scenes)["k3"] == -3


def test_resolve_floors_small_jumps_keep_the_basement_default() -> None:
    scenes = _scenes(
        {
            "ground": ("D Blok Giriş Kat", "D Blok", ["d1"]),
            "d1": ("D Blok -1 Koridor", "D Blok", []),
        }
    )
    assert resolve_floors(scenes)["d1"] == -1, "one floor down from 0 is fine"


def test_resolve_floors_glued_hyphens_follow_neighbours_ties_up() -> None:
    scenes = _scenes(
        {
            "b3": ("M Blok-3.Bodrum", "M Blok", ["lab"]),
            "lab": ("Mikroorganizma Lab.", "M Blok-3.K", []),
            "alone": ("Klinik Lab.", "M Blok-4.K", []),
        }
    )
    floors = resolve_floors(scenes)
    assert floors["lab"] == -3, "next to the -3 basement"
    assert floors["alone"] == 4, "nothing around it: upper floor"


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (("M Blok -1.Kat", "0"), "M"),
        (("Araştırma Lab.", "Kimya - M Blok"), "M"),
        (("G-H Blok Giriş", "H Blok"), "G-H"),
        (("M Blok-4.K",), "M"),
        (("Anatomi Lab", "Sağlık Bilimleri"), None),
    ],
)
def test_block_of_finds_the_first_named_block(
    texts: tuple[str, ...], expected: str | None
) -> None:
    assert block_of(*texts) == expected, f"{texts!r}"
