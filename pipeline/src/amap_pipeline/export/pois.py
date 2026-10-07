"""Points of interest from ``configs/pois.toml`` to ``data/out/pois.json``.

Each entry names the business's panorama (``node``) and, once the survey has
measured it, the tie point at its storefront (``landmark``): the pin stands
there. Until then a POI has no pin and the map shows it only in search.

    [[poi]]
    id = "burger-king"
    name = { tr = "Burger King", en = "Burger King" }
    category = "food"
    brand = "Burger King"
    aliases = ["bk", "hamburger"]
    node = "scene_428553"
    landmark = "poi.burger-king"     # survey tie point (data/derived/survey.json)
    building = "C"
    floor = 0
    verified = { checked = 2026-10-07, status = "open", source = "https://..." }
"""

import tomllib
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from amap_contracts.pois import Poi, PoiCollection

DEFAULT_POIS = Path(__file__).parents[3] / "configs" / "pois.toml"


def read_poi_config(path: Path = DEFAULT_POIS) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return list(tomllib.loads(path.read_text("utf-8")).get("poi", []))


def _verification(entry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    checked = entry["checked"]
    return {
        "checked": checked
        if isinstance(checked, date)
        else date.fromisoformat(checked),
        "status": entry["status"],
        "source": entry.get("source"),
    }


def _door(
    nodes: Mapping[str, Mapping[str, Any]], node: str | None
) -> tuple[float, float] | None:
    props = nodes.get(node or "")
    if props is None:
        return None
    anchor = props.get("anchor")
    measured = nodes.get(anchor) if anchor else props
    if measured is None:
        return None
    x, y, _ = measured["enu"]
    return round(float(x), 2), round(float(y), 2)


def build_pois(
    config: Iterable[Mapping[str, Any]],
    landmarks: Mapping[str, Mapping[str, Any]],
    nodes: Mapping[str, Mapping[str, Any]],
) -> tuple[PoiCollection, list[str]]:
    """Validated POIs plus warnings (unknown panoramas, unmeasured storefronts).

    ``nodes``: graph node properties by id. A POI whose storefront is not
    measured is pinned at its panorama's measured door instead (indoor
    panoramas borrow the position of the entrance they hang off).
    """
    warnings: list[str] = []
    pois: list[Poi] = []
    seen: set[str] = set()
    for entry in config:
        slug = str(entry["id"])
        if slug in seen:
            raise ValueError(f"duplicate POI id {slug}")
        seen.add(slug)
        node = entry.get("node")
        if node is not None and node not in nodes:
            warnings.append(f"{slug}: panorama {node} is not in the walking graph")
        pin: tuple[float, float] | None = None
        source: str | None = None
        if "pin" in entry:
            x, y = entry["pin"]
            pin, source = (float(x), float(y)), "manual"
        elif entry.get("landmark") and str(entry["landmark"]) in landmarks:
            lm = landmarks[str(entry["landmark"])]
            pin = (round(float(lm["x"]), 2), round(float(lm["y"]), 2))
            source = "storefront"
        else:
            if entry.get("landmark"):
                warnings.append(f"{slug}: storefront {entry['landmark']} not measured")
            door = _door(nodes, node)
            if door is not None:
                pin, source = door, "entrance"
        pois.append(
            Poi.model_validate(
                {
                    "id": slug,
                    "name": entry["name"],
                    "category": entry["category"],
                    "brand": entry.get("brand"),
                    "aliases": tuple(entry.get("aliases", ())),
                    "node_id": node,
                    "own_panorama": bool(entry.get("own_panorama", True)),
                    "pin_enu": pin,
                    "pin_source": source,
                    "building": entry.get("building"),
                    "floor": entry.get("floor"),
                    "verified": _verification(entry.get("verified")),
                }
            )
        )
    return PoiCollection(generated_at=datetime.now(UTC), pois=pois), warnings
