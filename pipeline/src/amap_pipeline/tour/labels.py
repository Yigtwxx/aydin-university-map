"""Floors and blocks named in tour labels ("M Blok -1.Kat", "FTR - M Blok 2.K").

The tour writes floors in several ways:

- ``"T Blok 2.Kat"``, ``"FTR - M Blok 2.K"``: a plain number is that floor;
- ``"2. Bod.Kat"``, ``"M Blok-3.Bodrum"``, ``"2.B"``: "Bodrum" (or "B") is a
  basement (-2, -3); a label saying Bodrum makes its area's floor one too;
- ``"Giriş Kat"``, ``"Zemin Kat"``, ``"0.Kat"``: the ground floor (0);
- ``"T Blok -2.Kat"``, ``"Kütüphane -1.Kat"``, ``"M Blok -5 Koridor"``: a
  hyphen right before the digit, not glued to a word, is a basement by
  default (**spaced**);
- ``"M Blok-3.K"``, ``"M Blok-5.K"``: a hyphen glued to a word is either a
  minus sign or a separator (**glued**, ambiguous).

The label decides first, then the area: a hyphenated label takes the sign of
its area when the area names the same floor plainly. :func:`resolve_floors`
settles the hyphens with the rest of the tour (see there).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from amap_contracts.places import is_generic_area

_SIGNED = re.compile(r"(?:^|\s)(-?)(\d+)\s*\.\s*(?:Kat|K\b|Floor)", re.IGNORECASE)
_GLUED = re.compile(r"-(\d+)\s*\.\s*(?:Kat|K\b|Floor)", re.IGNORECASE)
_BASEMENT = re.compile(r"(\d+)\s*\.\s*(?:Bod(?:rum)?|B)\b", re.IGNORECASE)
_BODRUM = re.compile(r"\bbod(?:rum)?\b", re.IGNORECASE)
_GROUND = re.compile(r"giriş kat|zemin kat|ground floor", re.IGNORECASE)
_LOOSE = re.compile(r"(?:^|\s)-(\d+)(?=\s|$)")
# "G-H Blok Giriş" names two adjoining blocks; "M Blok-4.K" one.
_BLOCK = re.compile(r"\b([A-Z](?:-[A-Z])?)\s*Blok\b")
# A default sign is overridden only to remove a jump this large.
JUMP_FLOORS = 3

Hyphen = Literal["certain", "spaced", "glued"]


@dataclass(frozen=True, slots=True)
class FloorReading:
    floor: int  # spaced: the basement (-n); glued: the upper floor (+n)
    hyphen: Hyphen = "certain"

    @property
    def certain(self) -> bool:
        return self.hyphen == "certain"


def _read(text: str, basement: bool, loose: bool) -> FloorReading | None:
    """``basement``: the scene is named a basement, so hyphens are minus signs."""
    match = _BASEMENT.search(text)
    if match:
        return FloorReading(-int(match.group(1)))
    match = _SIGNED.search(text)
    if match and not match.group(1):
        return FloorReading(int(match.group(2)))
    hyphen: Hyphen | None = None
    number = 0
    if match:
        hyphen, number = "spaced", int(match.group(2))
    elif m := _GLUED.search(text):
        hyphen, number = "glued", int(m.group(1))
    elif loose and (m := _LOOSE.search(text)):
        hyphen, number = "spaced", int(m.group(1))
    if hyphen is not None and number != 0:
        if basement:
            return FloorReading(-number)
        return FloorReading(-number if hyphen == "spaced" else number, hyphen)
    if hyphen is not None or _GROUND.search(text):
        return FloorReading(0)
    return None


def read_floor(label: str, area: str = "") -> FloorReading | None:
    """What a scene's label (else its area) says about its floor."""
    basement = bool(_BODRUM.search(label))
    own = _read(label, basement, loose=True)
    if own is not None and own.certain:
        return own
    zone = _read(area, basement, loose=False)
    if own is None:
        return zone
    if zone is not None and zone.certain and abs(zone.floor) == abs(own.floor):
        return zone  # the area names the same floor plainly: its sign
    return own


def floor_of(label: str, area: str = "") -> int | None:
    """The floor without the rest of the tour: hyphens at their defaults."""
    reading = read_floor(label, area)
    return reading.floor if reading else None


def _building_key(scene: Mapping[str, Any]) -> str | None:
    label, area = scene["label"]["tr"], scene["area"]["tr"]
    block = block_of(label, area)
    if block:
        return f"blok:{block}"
    return None if is_generic_area(area) else f"area:{area.strip()}"


def resolve_floors(
    scenes: Mapping[str, Mapping[str, Any]], notes: dict[str, str] | None = None
) -> dict[str, int]:
    """Scene -> floor for every scene whose label or area names one.

    1. A building that writes floor n plainly elsewhere ("Kütüphane 1.Kat")
       makes its hyphenated n a basement ("Kütüphane -1.Kat"): certain.
    2. Spaced hyphens are basements by default; glued ones take the sign that
       keeps them closest to their linked spots (certain ones, the spaced
       defaults, then glued ones decided before them, round by round; ties
       and silence: upper floor).
    3. A spaced default flips only when its sign would jump three floors or
       more to a linked spot of certain floor, and the other sign makes the
       total jump to those spots smaller.

    ``notes`` (when given) receives why each hyphenated floor came out so.
    """
    notes = {} if notes is None else notes
    readings = {
        name: reading
        for name, scene in scenes.items()
        if (reading := read_floor(scene["label"]["tr"], scene["area"]["tr"]))
    }
    uppers: dict[str, set[int]] = {}
    for name, r in readings.items():
        key = _building_key(scenes[name])
        if r.certain and r.floor > 0 and key:
            uppers.setdefault(key, set()).add(r.floor)
    floors = {n: r.floor for n, r in readings.items() if r.certain}
    for name, r in sorted(readings.items()):
        key = _building_key(scenes[name])
        if not r.certain and key and abs(r.floor) in uppers.get(key, set()):
            floors[name] = -abs(r.floor)
            notes[name] = f"basement: the building has floor {abs(r.floor)} too"
    certain = dict(floors)

    def jumps(floor: int, around: list[int]) -> tuple[int, int]:
        gaps = [abs(floor - f) for f in around]
        return max(gaps, default=0), sum(gaps)

    spaced = sorted(n for n, r in readings.items() if r.hyphen == "spaced")
    for name in (n for n in spaced if n not in floors):
        down = readings[name].floor
        around = [certain[m] for m in scenes[name]["links"] if m in certain]
        worst, total = jumps(down, around)
        _, flipped = jumps(-down, around)
        if worst >= JUMP_FLOORS and flipped < total:
            floors[name] = -down
            notes[name] = f"upper floor: {down} would jump {worst} floors"
        else:
            floors[name] = down
            notes[name] = "basement (spaced hyphen)"
    pending = sorted(
        n for n, r in readings.items() if r.hyphen == "glued" and n not in floors
    )
    while pending:
        decided: dict[str, int] = {}
        for name in pending:
            around = [floors[m] for m in scenes[name]["links"] if m in floors]
            if not around:
                continue
            up = readings[name].floor
            rise, fall = jumps(up, around)[1], jumps(-up, around)[1]
            decided[name] = -up if fall < rise else up
            notes[name] = "follows its neighbours" + (" (tie)" if fall == rise else "")
        if not decided:
            break
        floors.update(decided)
        pending = [n for n in pending if n not in decided]
    for name in pending:
        floors[name] = readings[name].floor
        notes[name] = "upper floor: no floor around it"
    return floors


def block_of(*texts: str) -> str | None:
    """Block code ("M", "G-H") from the first text that names one."""
    for text in texts:
        match = _BLOCK.search(text)
        if match:
            return match.group(1)
    return None
