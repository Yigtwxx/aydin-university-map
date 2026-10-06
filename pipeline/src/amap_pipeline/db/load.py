"""Load pipeline outputs (``data/out``) into the ``amap`` schema.

Each load replaces the graph, buildings and places in one transaction, so the
API never sees half a graph. The assistant's ``chunks`` are loaded separately
(``amap rag load``).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from shapely.geometry import LineString, Point, Polygon

from amap_contracts.graph import Graph
from amap_contracts.places import build_places
from amap_pipeline.geo.osm import LocalProjector

_BLOCK_CODE = re.compile(r"(?:^|\s)([A-ZÇĞİÖŞÜ](?:-[A-ZÇĞİÖŞÜ])?)\s+(?:Binası|Blok)")


@dataclass(frozen=True, slots=True)
class LoadCounts:
    buildings: int
    nodes: int
    edges: int
    places: int


def building_code(name: str | None) -> str | None:
    """``"İstanbul Aydın Üniversitesi A Binası"`` -> ``"A"``."""
    match = _BLOCK_CODE.search(name or "")
    return match.group(1) if match else None


def building_rows(
    buildings: list[dict[str, Any]], projector: LocalProjector
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for b in buildings:
        ring = [projector.to_wgs84(float(x), float(y)) for x, y in b["outline"]]
        footprint = Polygon(ring)
        if not footprint.is_valid or footprint.is_empty:
            continue
        rows.append(
            (
                str(b["id"]),
                building_code(b.get("name")) if b.get("campus") else None,
                b.get("name"),
                bool(b.get("campus")),
                float(b["height_m"]),
                str(b.get("height_source", "default")),
                footprint.wkt,
                json.dumps(b["outline"]),
            )
        )
    return rows


def load_outputs(conn: psycopg.Connection, out_dir: Path) -> LoadCounts:
    graph = Graph.from_geojson(
        json.loads((out_dir / "graph.geojson").read_text("utf-8"))
    )
    buildings = json.loads((out_dir / "buildings.json").read_text("utf-8"))["buildings"]
    by_id = {n.id: n for n in graph.nodes}
    places = build_places(graph.nodes)
    b_rows = building_rows(buildings, LocalProjector())

    with conn.transaction():
        conn.execute("delete from amap.edges")
        conn.execute("delete from amap.nodes")
        conn.execute("delete from amap.places")
        conn.execute("delete from amap.buildings")
        with conn.cursor() as cur:
            cur.executemany(
                "insert into amap.buildings (id, code, name, campus, height_m, "
                "height_source, footprint, outline_local) values "
                "(%s, %s, %s, %s, %s, %s, extensions.st_geomfromtext(%s, 4326), %s)",
                b_rows,
            )
            cur.executemany(
                "insert into amap.nodes (id, kind, building, floor, label_tr, "
                "label_en, area_tr, area_en, heading_deg, pose_source, enu, geom) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "extensions.st_geomfromtext(%s, 4326))",
                [
                    (
                        n.id,
                        n.kind.value,
                        n.building,
                        n.floor,
                        n.label.tr,
                        n.label.en,
                        n.area.tr,
                        n.area.en,
                        n.heading_deg,
                        n.pose_source.value,
                        list(n.enu),
                        Point(n.lng, n.lat, n.alt_m).wkt,
                    )
                    for n in graph.nodes
                ],
            )
            cur.executemany(
                "insert into amap.edges (id, source, target, kind, origin, "
                "length_m, cost_s, length_source, geom) values "
                "(%s, %s, %s, %s, %s, %s, %s, %s, "
                "extensions.st_geomfromtext(%s, 4326))",
                [
                    (
                        e.id,
                        e.source,
                        e.target,
                        e.kind.value,
                        e.origin.value,
                        e.length_m,
                        e.cost_s,
                        e.length_source.value,
                        LineString(
                            [
                                (
                                    by_id[e.source].lng,
                                    by_id[e.source].lat,
                                    by_id[e.source].alt_m,
                                ),
                                (
                                    by_id[e.target].lng,
                                    by_id[e.target].lat,
                                    by_id[e.target].alt_m,
                                ),
                            ]
                        ).wkt,
                    )
                    for e in graph.edges
                ],
            )
            cur.executemany(
                "insert into amap.places (id, name_tr, name_en, kind, building, "
                "node_ids, search_key) values (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        p.id,
                        p.name_tr,
                        p.name_en,
                        p.kind.value,
                        p.building,
                        list(p.node_ids),
                        p.key,
                    )
                    for p in places
                ],
            )
    return LoadCounts(len(b_rows), len(graph.nodes), len(graph.edges), len(places))
