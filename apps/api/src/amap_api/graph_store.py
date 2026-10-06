"""Load the walking graph (contracts GeoJSON) into NetworkX once per process."""

import json
from dataclasses import dataclass
from pathlib import Path

import httpx
import networkx as nx

from amap_contracts.graph import Graph, Node


@dataclass(frozen=True, slots=True)
class GraphStore:
    graph: Graph
    nx_graph: nx.Graph
    nodes: dict[str, Node]

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
            )
        return cls(graph=graph, nx_graph=g, nodes={n.id: n for n in graph.nodes})


def load_graph(source: str) -> GraphStore:
    """Read ``graph.geojson`` from a local path or an http(s) URL."""
    if source.startswith(("http://", "https://")):
        response = httpx.get(source, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
    else:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    return GraphStore.from_graph(Graph.from_geojson(data))
