"""The campus block registry: which footprint is which block, and how tall.

OSM names a handful of campus buildings and draws some blocks as one
footprint; the tour, the survey and the signs on the walls tell them apart.
``configs/campus.toml``::

    [blocks.A]
    name = { tr = "A Blok", en = "A Block" }
    osm = ["way/1550440571"]          # footprints that are this block
    levels = 4                        # storeys above ground, counted on panoramas
    height_m = 15.2                   # roof line measured on panoramas
    evidence = [{ scene = "scene_428525", ath = 95.0, note = "A BLOK sign" }]

    [blocks.G]
    name = { tr = "G Blok", en = "G Block" }
    split_from = "way/1550440570"     # OSM drew G inside B's footprint
    outline = [[-30.0, 50.0], [-20.0, 50.0], [-20.0, 60.0], [-30.0, 60.0]]

    [blocks.C]
    name = { tr = "C Blok", en = "C Block" }
    outline = [[...]]                 # a footprint OSM lacks

    [blocks.D]
    osm = ["way/1550439994"]
    outline = [[...]]                 # OSM's footprint is wrong: replace it

A block's map name becomes "İstanbul Aydın Üniversitesi <code> Binası" (or its
own Turkish name when the code is not a letter), the form every reader already
recognises as a campus block; the code itself travels as ``code``.
"""

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from amap_contracts.facade import Facade
from amap_pipeline.geo.osm import Building

DEFAULT_CAMPUS = Path(__file__).parents[3] / "configs" / "campus.toml"
STOREY_M = 3.4
_LETTER = re.compile(r"^[A-ZÇĞİÖŞÜ](-[A-ZÇĞİÖŞÜ])?$")


@dataclass(frozen=True, slots=True)
class Block:
    code: str
    name_tr: str
    name_en: str
    osm: tuple[str, ...] = ()
    split_from: str | None = None
    outline: Polygon | None = None
    levels: float | None = None
    height_m: float | None = None
    base_m: float | None = None
    height_source: str = "pano"
    facade: Mapping[str, Any] = field(default_factory=dict)
    # A gate hall walked through (turnstiles under its roof): the walking
    # graph does not route round it as it does round a building.
    walk_through: bool = False

    @property
    def map_name(self) -> str:
        if _LETTER.match(self.code):
            return f"İstanbul Aydın Üniversitesi {self.code} Binası"
        return f"İstanbul Aydın Üniversitesi {self.name_tr}"

    def registry(self) -> dict[str, Any]:
        facts: dict[str, Any] = {"code": self.code}
        if self.height_m is not None:
            facts["height_m"] = self.height_m
            facts["height_source"] = self.height_source
        elif self.levels is not None:
            facts["height_m"] = round(self.levels * STOREY_M + 0.6, 2)
            facts["height_source"] = self.height_source
        if self.levels is not None:
            facts["levels"] = int(self.levels)
        if self.base_m is not None:
            facts["base_m"] = self.base_m
        if self.facade:
            facts["facade"] = dict(self.facade)
        return facts


@dataclass(frozen=True, slots=True)
class Registry:
    blocks: dict[str, Block]
    remove: tuple[str, ...] = ()  # footprints a block replaces outright


def _polygon(code: str, points: Sequence[Sequence[float]]) -> Polygon:
    poly = Polygon([(float(x), float(y)) for x, y in points])
    if not poly.is_valid or poly.area < 4.0:
        raise ValueError(f"block {code}: invalid outline")
    return poly


def _facade(code: str, entry: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validated facade recipe, defaults filled in (empty: none surveyed yet)."""
    if not entry:
        return {}
    try:
        return Facade.model_validate(entry).model_dump(mode="json")
    except ValueError as exc:
        raise ValueError(f"block {code}: invalid facade: {exc}") from exc


def parse_campus(data: Mapping[str, Any]) -> Registry:
    blocks: dict[str, Block] = {}
    for code, entry in data.get("blocks", {}).items():
        name = entry.get("name", {})
        outline = entry.get("outline")
        osm = tuple(str(i) for i in entry.get("osm", ()))
        split_from = entry.get("split_from")
        if not osm and outline is None:
            raise ValueError(f"block {code}: give osm footprints or an outline")
        if split_from is not None and outline is None:
            raise ValueError(f"block {code}: split_from needs the part's outline")
        blocks[str(code)] = Block(
            code=str(code),
            name_tr=str(name.get("tr", f"{code} Blok")),
            name_en=str(name.get("en", f"{code} Block")),
            osm=osm,
            split_from=str(split_from) if split_from else None,
            outline=None if outline is None else _polygon(str(code), outline),
            levels=float(entry["levels"]) if "levels" in entry else None,
            height_m=float(entry["height_m"]) if "height_m" in entry else None,
            base_m=float(entry["base_m"]) if "base_m" in entry else None,
            height_source=str(entry.get("height_source", "pano")),
            facade=_facade(str(code), entry.get("facade")),
            walk_through=bool(entry.get("walk_through", False)),
        )
    return Registry(blocks=blocks, remove=tuple(str(i) for i in data.get("remove", ())))


def load_campus(path: Path | None = DEFAULT_CAMPUS) -> Registry:
    if path is None or not path.is_file():
        return Registry(blocks={})
    return parse_campus(tomllib.loads(path.read_text("utf-8")))


def _largest(geometry: BaseGeometry) -> Polygon | None:
    if geometry.is_empty:
        return None
    if isinstance(geometry, Polygon):
        return geometry
    if isinstance(geometry, MultiPolygon):
        return max(geometry.geoms, key=lambda g: g.area)
    return None


def _numbered_like(poly: Polygon, source: BaseGeometry) -> Polygon:
    """``poly`` with its ring turned and started like ``source``'s.

    Survey sightings name corners by index ("8421#2"), so a footprint with a
    block cut out of it keeps the numbers of the corners the cut left alone.
    """
    if not isinstance(source, Polygon):
        return poly
    ring = list(poly.exterior.coords)[:-1]
    if poly.exterior.is_ccw != source.exterior.is_ccw:
        ring.reverse()
    for corner in list(source.exterior.coords)[:-1]:
        for i, (x, y) in enumerate(ring):
            if abs(x - corner[0]) < 1e-6 and abs(y - corner[1]) < 1e-6:
                return Polygon(ring[i:] + ring[:i], [h.coords for h in poly.interiors])
    return poly


def apply_campus(buildings: Sequence[Building], registry: Registry) -> list[Building]:
    """Name, measure and split the campus blocks; add the ones OSM lacks."""
    by_id = {b.osm_id: b for b in buildings}
    owner: dict[str, Block] = {}
    for block in registry.blocks.values():
        for osm_id in block.osm:
            if osm_id not in by_id:
                raise ValueError(f"block {block.code}: no footprint {osm_id}")
            if osm_id in owner:
                raise ValueError(f"{osm_id} belongs to {owner[osm_id].code} too")
            owner[osm_id] = block

    def own_outline(b: Building) -> BaseGeometry:
        """A footprint OSM drew wrong is replaced by its block's outline,
        before anything is carved out of it."""
        block = owner.get(b.osm_id)
        if block is not None and block.outline is not None:
            return block.outline
        return b.outline

    carved: dict[str, Polygon] = {}
    for block in registry.blocks.values():
        if block.split_from is None or block.outline is None:
            continue
        parent = by_id.get(block.split_from)
        if parent is None:
            raise ValueError(f"block {block.code}: no footprint {block.split_from}")
        rest = carved.get(parent.osm_id, own_outline(parent)).difference(block.outline)
        remainder = _largest(rest)
        if remainder is None or remainder.area < 4.0:
            raise ValueError(f"block {block.code}: nothing left of {parent.osm_id}")
        carved[parent.osm_id] = _numbered_like(remainder, own_outline(parent))
    out: list[Building] = []
    for b in buildings:
        if b.osm_id in registry.remove:
            continue
        outline = carved.get(b.osm_id, own_outline(b))
        block = owner.get(b.osm_id)
        if block is None:
            out.append(replace(b, outline=outline))
            continue
        out.append(
            replace(
                b,
                name=block.map_name,
                outline=outline,
                levels=block.levels if block.levels is not None else b.levels,
                registry=block.registry(),
            )
        )
    for block in registry.blocks.values():
        if block.outline is None or (block.osm and block.split_from is None):
            continue
        out.append(
            Building(
                osm_id=f"campus/{block.code}",
                name=block.map_name,
                levels=block.levels,
                outline=block.outline,
                tags={"building": "university"},
                registry=block.registry(),
            )
        )
    return out
