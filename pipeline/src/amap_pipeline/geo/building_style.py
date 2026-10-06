"""What each building is, how tall it is and what its roof looks like.

The web map gives every style its own facade (window rhythm, glazing,
cladding) and roof, so the neighbourhood reads as İstanbul rather than as
identical grey boxes. Most footprints are only ``building=yes``; the style is
inferred, in order of trust, from:

1. the campus name (Aydın University blocks keep their ochre identity);
2. specific ``building=*`` values (mosque, school, hangar, ...);
3. the building's name ("... Camii", "... Lisesi", "Turkish Technic");
4. ``amenity``/``shop``/``office`` tags on the footprint;
5. POIs mapped inside the footprint (a car dealer, shops at street level);
6. the land use it stands in (industrial estate, airport apron, school);
7. its footprint (big and low = warehouse, tiny = house).

Heights use ``building:levels`` when mapped; otherwise a per-style typical
storey count, varied deterministically per building (a stable hash of the OSM
id), so re-exports never reshuffle the skyline.
"""

import hashlib
import random
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from amap_contracts.text import lower_tr
from amap_pipeline.geo.context import Context
from amap_pipeline.geo.osm import Building

CAMPUS_NAME = "Aydın Üniversitesi"

STYLES = (
    "campus",
    "apartment",
    "house",
    "retail",
    "showroom",
    "office",
    "industrial",
    "hangar",
    "school",
    "dormitory",
    "worship",
    "hospital",
    "hotel",
    "sports",
    "canopy",
)


@dataclass(frozen=True, slots=True)
class StyleSpec:
    levels: tuple[int, int]  # inclusive range of typical storeys
    storey_m: float
    ground_m: float  # extra height of the ground floor (shops, lobbies)
    fixed_m: float | None = None  # single-volume buildings (sheds, hangars)


SPECS: dict[str, StyleSpec] = {
    "campus": StyleSpec((4, 5), 3.4, 0.6),
    "apartment": StyleSpec((4, 7), 3.0, 0.4),
    "house": StyleSpec((1, 3), 3.0, 0.0),
    "retail": StyleSpec((2, 3), 4.6, 0.8),
    "showroom": StyleSpec((1, 2), 4.8, 1.2),
    "office": StyleSpec((4, 8), 3.6, 0.8),
    "industrial": StyleSpec((1, 1), 0.0, 0.0, fixed_m=8.0),
    "hangar": StyleSpec((1, 1), 0.0, 0.0, fixed_m=14.0),
    "school": StyleSpec((3, 4), 3.6, 0.4),
    "dormitory": StyleSpec((5, 7), 3.1, 0.6),
    "worship": StyleSpec((1, 1), 0.0, 0.0, fixed_m=9.0),
    "hospital": StyleSpec((5, 7), 3.8, 0.8),
    "hotel": StyleSpec((6, 9), 3.2, 1.0),
    "sports": StyleSpec((1, 1), 0.0, 0.0, fixed_m=12.0),
    "canopy": StyleSpec((1, 1), 0.0, 0.0, fixed_m=5.0),
}

BUILDING_TAG_STYLES = {
    "mosque": "worship",
    "church": "worship",
    "chapel": "worship",
    "synagogue": "worship",
    "religious": "worship",
    "school": "school",
    "university": "school",
    "college": "school",
    "kindergarten": "school",
    "dormitory": "dormitory",
    "hospital": "hospital",
    "clinic": "hospital",
    "hotel": "hotel",
    "office": "office",
    "government": "office",
    "civic": "office",
    "public": "office",
    "commercial": "retail",
    "retail": "retail",
    "supermarket": "retail",
    "kiosk": "retail",
    "industrial": "industrial",
    "warehouse": "industrial",
    "factory": "industrial",
    "manufacture": "industrial",
    "service": "industrial",
    "garage": "industrial",
    "garages": "industrial",
    "hangar": "hangar",
    "roof": "canopy",
    "carport": "canopy",
    "sports_hall": "sports",
    "sports_centre": "sports",
    "stadium": "sports",
    "grandstand": "sports",
}
RESIDENTIAL_TAGS = {
    "apartments": "apartment",
    "residential": "apartment",
    "house": "house",
    "detached": "house",
    "semidetached_house": "house",
    "terrace": "house",
    "bungalow": "house",
}

# Lowercased (Turkish rules) name fragments, checked in order.
NAME_STYLES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("cami", "mescit", "mosque"), "worship"),
    (("hastane", "hospital", "tıp merkezi", "klinik", "sağlık"), "hospital"),
    (("yurdu", "yurt ", "dormitory"), "dormitory"),
    (
        ("okul", "lise", "kolej", "anadolu", "imam hatip", "school", "akademi"),
        "school",
    ),
    (("otel", "hotel", "suites"), "hotel"),
    (("avm", "alışveriş", "mall", "outlet", "market", "plaza"), "retail"),
    (("stad", "spor", "arena", "sports"), "sports"),
    (("technic", "teknik", "jet", "cargo", "kargo", "hangar", "havacılık"), "hangar"),
    (("fabrika", "depo", "lojistik", "sanayi"), "industrial"),
)

AMENITY_STYLES = {
    "place_of_worship": "worship",
    "hospital": "hospital",
    "clinic": "hospital",
    "school": "school",
    "university": "school",
    "college": "school",
    "kindergarten": "school",
    "townhall": "office",
    "bank": "office",
    "fuel": "canopy",
}

# Land use the building stands in (smallest area containing its centroid).
AREA_STYLES = {
    "landuse:industrial": "industrial",
    "aeroway:aerodrome": "hangar",
    "aeroway:apron": "hangar",
    "landuse:commercial": "office",
    "landuse:retail": "retail",
    "amenity:school": "school",
    "amenity:university": "school",
    "amenity:college": "school",
    "amenity:kindergarten": "school",
    "amenity:hospital": "hospital",
    "amenity:place_of_worship": "worship",
    "leisure:sports_centre": "sports",
    "leisure:stadium": "sports",
}

RESIDENTIAL_SHOP_POIS = ("shop:", "amenity:cafe", "amenity:restaurant", "amenity:bank")

# Without imagery evidence, the share of homes with a terracotta tiled roof.
# Around Beşyol most blocks are flat-roofed; tiles cluster in older streets.
HIPPED_SHARE = 0.3
MIN_RECTANGULARITY = 0.84
# Blocks this close to a main street have shops at street level this often.
SHOP_STREET_M = 10.0
SHOP_STREET_SHARE = 0.7
# Flat-roofed blocks with a set-back top floor (çekme kat).
PENTHOUSE_SHARE = 0.28
PENTHOUSE_INSET_M = 2.2
PENTHOUSE_M = 2.9


def _rng(osm_id: str) -> random.Random:
    digest = hashlib.sha1(osm_id.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:12], 16))


def _name_style(name: str | None) -> str | None:
    if not name:
        return None
    lowered = lower_tr(name)
    for fragments, style in NAME_STYLES:
        if any(f in lowered for f in fragments):
            return style
    return None


def _poi_style(kinds: list[str]) -> str | None:
    if "shop:car" in kinds or "shop:car_repair" in kinds:
        return "showroom"
    if any(k in ("shop:mall", "shop:department_store") for k in kinds):
        return "retail"
    if "shop:supermarket" in kinds:
        return "retail"
    if any(k == "amenity:place_of_worship" for k in kinds):
        return "worship"
    if any(k.startswith("tourism:hotel") for k in kinds):
        return "hotel"
    return None


def classify(building: Building, context: Context | None = None) -> str:
    tags = building.tags
    name = building.name
    if name and CAMPUS_NAME in name:
        return "campus"
    value = tags.get("building", "yes")
    if value in BUILDING_TAG_STYLES:
        return BUILDING_TAG_STYLES[value]
    by_name = _name_style(name)
    if by_name:
        return by_name
    if tags.get("shop") == "car":
        return "showroom"
    if tags.get("shop") in ("mall", "department_store", "supermarket"):
        return "retail"
    if tags.get("amenity") in AMENITY_STYLES:
        return AMENITY_STYLES[tags["amenity"]]
    if "office" in tags:
        return "office"
    if value in RESIDENTIAL_TAGS:
        return RESIDENTIAL_TAGS[value]
    area = building.outline.area
    if context is not None:
        poi = _poi_style([p.kind for p in context.pois_in(building.outline)])
        if poi:
            return poi
        for found in context.areas_at(building.outline.representative_point()):
            style = AREA_STYLES.get(found.kind)
            if style is None:
                continue
            # Small sheds on a school ground or an apron are not schools.
            if style in ("school", "hospital") and area < 150:
                return "house"
            if style == "hangar" and area < 1200:
                return "industrial"
            return style
    if area > 2600 and (building.levels or 1) <= 2:
        return "industrial"
    if area < 110:
        return "house"
    return "apartment"


def has_street_shops(
    building: Building,
    style: str,
    context: Context | None,
    streets: BaseGeometry | None = None,
) -> bool:
    """Apartment blocks with shops or cafés at street level.

    Mapped shops inside the footprint decide first; otherwise blocks along a
    main street usually have a shop front (the İstanbul street pattern).
    """
    if style != "apartment":
        return False
    if context is not None:
        kinds = [p.kind for p in context.pois_in(building.outline)]
        if any(k.startswith(RESIDENTIAL_SHOP_POIS) for k in kinds):
            return True
    if streets is None or building.outline.distance(streets) > SHOP_STREET_M:
        return False
    return _rng(building.osm_id + "/shops").random() < SHOP_STREET_SHARE


def height_of(building: Building, style: str) -> tuple[float, int, str]:
    """(height in metres, storeys, source) for ``building`` drawn as ``style``."""
    spec = SPECS[style]
    tags = building.tags
    try:
        mapped = float(tags["height"].replace("m", "").strip())
    except (KeyError, ValueError):
        mapped = None
    if mapped and mapped > 0:
        storeys = max(1, round(mapped / max(spec.storey_m, 3.0)))
        return round(mapped, 2), storeys, "osm_height"
    if building.levels and building.levels > 0:
        storeys = round(building.levels)
        if spec.fixed_m is not None:
            return max(spec.fixed_m, storeys * 4.0), storeys, "osm_levels"
        height = storeys * spec.storey_m + spec.ground_m
        return round(height, 2), storeys, "osm_levels"
    rng = _rng(building.osm_id)
    if spec.fixed_m is not None:
        # Bigger sheds and halls stand taller.
        scale = min(1.0 + building.outline.area / 12000.0, 1.45)
        return round(spec.fixed_m * scale * rng.uniform(0.9, 1.1), 2), 1, "default"
    low, high = spec.levels
    # Bias apartment blocks to the common five storeys of the area.
    storeys = round(rng.triangular(low, high, (low + high) / 2)) if high > low else low
    return round(storeys * spec.storey_m + spec.ground_m, 2), storeys, "default"


def _obb(outline: Polygon) -> tuple[list[tuple[float, float]], float]:
    """Corners of the minimum rotated rectangle (long side first) and fill ratio."""
    rect = shapely.minimum_rotated_rectangle(outline)
    if not isinstance(rect, Polygon):  # degenerate (collinear) footprint
        return [], 0.0
    coords = list(rect.exterior.coords)[:4]
    if len(coords) < 4:
        return [], 0.0
    (x0, y0), (x1, y1), (x2, y2) = coords[0], coords[1], coords[2]
    if (x1 - x0) ** 2 + (y1 - y0) ** 2 < (x2 - x1) ** 2 + (y2 - y1) ** 2:
        coords = coords[1:] + coords[:1]
    fill = outline.area / rect.area if rect.area > 0 else 0.0
    return [(round(x, 2), round(y, 2)) for x, y in coords], fill


def _short_side(corners: list[tuple[float, float]]) -> float:
    (x1, y1), (x2, y2) = corners[1], corners[2]
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


def _inset_ring(outline: Polygon, inset_m: float) -> list[list[float]] | None:
    inner = outline.buffer(-inset_m, join_style="mitre")
    if inner.is_empty or inner.geom_type != "Polygon" or inner.area < 4.0:
        return None
    assert isinstance(inner, Polygon)
    return [[round(x, 2), round(y, 2)] for x, y in inner.exterior.coords]


def roof_of(building: Building, style: str, height_m: float) -> dict[str, Any]:
    """Roof description the web turns into geometry."""
    outline = building.outline
    rng = _rng(building.osm_id + "/roof")
    corners, fill = _obb(outline)
    shape = building.tags.get("roof:shape")
    if style == "worship":
        circle = shapely.maximum_inscribed_circle(outline)
        coords = list(circle.coords)
        (cx, cy), (ex, ey) = coords[0], coords[1]
        radius = ((ex - cx) ** 2 + (ey - cy) ** 2) ** 0.5
        # One minaret at the footprint corner farthest from the dome centre.
        ring = list(outline.exterior.coords)[:-1]
        mx, my = max(ring, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        return {
            "shape": "dome",
            "centre": [round(cx, 2), round(cy, 2)],
            "radius": round(radius * 0.92, 2),
            "minaret": [round(mx, 2), round(my, 2)],
            "minaret_m": round(max(24.0, height_m * 3.2), 1),
        }
    if style == "hangar" and shape in ("round", "barrel") and corners and fill >= 0.8:
        return {
            "shape": "barrel",
            "obb": corners,
            "rise": round(min(_short_side(corners) * 0.14, 7.0), 2),
        }
    residential = style in ("apartment", "house", "dormitory")
    hipped = shape in ("hipped", "gabled", "pyramidal") or (
        shape is None and residential and rng.random() < HIPPED_SHARE
    )
    if (
        residential
        and hipped
        and corners
        and fill >= MIN_RECTANGULARITY
        and outline.area < 2200
    ):
        short = _short_side(corners)
        return {
            "shape": "hipped",
            "obb": corners,
            "rise": round(min(max(short * 0.28, 1.4), 3.6), 2),
            "overhang": 0.45,
        }
    roof: dict[str, Any] = {"shape": "flat"}
    inset = _inset_ring(outline, 0.35)
    if inset and style not in ("canopy", "industrial", "hangar"):
        roof["parapet"] = inset
    if style in ("apartment", "dormitory", "hotel") and outline.area > 160:
        top = _inset_ring(outline, PENTHOUSE_INSET_M)
        if top and rng.random() < PENTHOUSE_SHARE:
            roof["penthouse"] = top
            roof["penthouse_m"] = PENTHOUSE_M
    # Rooftop clutter: water heaters on homes, plant rooms on bigger buildings.
    area = outline.area
    if style in ("apartment", "dormitory", "house"):
        roof["units"] = rng.randint(1, 3) if area > 80 else 0
        roof["unit_kind"] = "solar"
    elif style in ("retail", "office", "hospital", "hotel", "school", "campus"):
        roof["units"] = min(2 + int(area // 600), 7)
        roof["unit_kind"] = "hvac"
    return roof


def style_records(
    buildings: Iterable[Building],
    context: Context | None,
    streets: BaseGeometry | None = None,
) -> list[dict[str, Any]]:
    """Style, height and roof per building, keyed like massing features."""
    records: list[dict[str, Any]] = []
    for b in buildings:
        style = classify(b, context)
        height, storeys, source = height_of(b, style)
        record: dict[str, Any] = {
            "style": style,
            "height_m": height,
            "levels": storeys,
            "height_source": source,
            "roof": roof_of(b, style, height),
        }
        if style == "canopy":
            record["base_m"] = round(max(height - 0.8, 2.5), 2)
        if has_street_shops(b, style, context, streets):
            record["shops"] = True
        records.append(record)
    return records
