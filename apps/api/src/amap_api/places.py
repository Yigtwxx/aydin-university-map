"""Places for the API: the shared contracts logic over the loaded graph."""

from collections.abc import Iterable

from amap_api.graph_store import GraphStore
from amap_contracts.places import Place, search_places
from amap_contracts.places import build_places as _build_places
from amap_contracts.pois import Poi

__all__ = ["Place", "build_places", "search_places"]


def build_places(store: GraphStore, pois: Iterable[Poi] = ()) -> list[Place]:
    return _build_places(store.graph.nodes, pois)
