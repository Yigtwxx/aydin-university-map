"""Load the walking graph (contracts GeoJSON) into NetworkX once per process."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import networkx as nx

from amap_contracts.graph import Graph, Node
from amap_contracts.pois import Poi, PoiCollection


def _indoor_clusters(graph: Graph, nodes: dict[str, Node]) -> dict[str, int]:
    """Approximate (indoor) node -> id of the indoor network it belongs to.

    Two indoor spots are in one cluster when indoor links join them without
    stepping onto a measured node: the inside of one building (or of blocks
    the tour joins indoors).
    """
    root = {n.id: n.id for n in graph.nodes if n.approximate}

    def find(node_id: str) -> str:
        while root[node_id] != node_id:
            root[node_id] = root[root[node_id]]
            node_id = root[node_id]
        return node_id

    for edge in graph.edges:
        if nodes[edge.source].approximate and nodes[edge.target].approximate:
            a, b = sorted((find(edge.source), find(edge.target)))
            root[b] = a
    ids: dict[str, int] = {}
    return {n: ids.setdefault(find(n), len(ids)) for n in sorted(root)}


@dataclass(frozen=True, slots=True)
class GraphStore:
    graph: Graph
    nx_graph: nx.Graph
    nodes: dict[str, Node]
    indoor_cluster: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_graph(cls, graph: Graph) -> "GraphStore":
        g = nx.Graph()
        for node in graph.nodes:
            g.add_node(node.id)
        for edge in graph.edges:
            g.add_edge(
                edge.source,
                edge.target,
                id=edge.id,
                length_m=edge.length_m,
                cost_s=edge.cost_s,
                kind=edge.kind.value,
                source=edge.source,
                path_enu=edge.path_enu,
                length_source=edge.length_source.value,
                passage=edge.passage,
                crosses=edge.crosses.value if edge.crosses else None,
            )
        nodes = {n.id: n for n in graph.nodes}
        return cls(
            graph=graph,
            nx_graph=g,
            nodes=nodes,
            indoor_cluster=_indoor_clusters(graph, nodes),
        )


def load_graph(source: str) -> GraphStore:
    """Read ``graph.geojson`` from a local path or an http(s) URL."""
    if source.startswith(("http://", "https://")):
        response = httpx.get(source, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
    else:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    return GraphStore.from_graph(Graph.from_geojson(data))


def source_version(source: str) -> str | None:
    """A token that changes whenever the graph at ``source`` does.

    A local file's modification time and size; for a URL its ``ETag`` (or
    ``Last-Modified``) from a HEAD request. None when it cannot be told.
    """
    try:
        if source.startswith(("http://", "https://")):
            response = httpx.head(source, timeout=5.0, follow_redirects=True)
            if response.status_code != 200:
                return None
            return response.headers.get("etag") or response.headers.get("last-modified")
        stat = Path(source).stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"
    except (OSError, httpx.HTTPError):
        return None


def load_pois(source: str) -> list[Poi]:
    """Read ``pois.json`` (path or URL); a missing file means no POIs."""
    if source.startswith(("http://", "https://")):
        response = httpx.get(source, timeout=30.0, follow_redirects=True)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        text = response.text
    else:
        path = Path(source)
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
    return PoiCollection.model_validate_json(text).pois
