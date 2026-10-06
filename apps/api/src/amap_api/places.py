"""Searchable places derived from panorama labels (Turkish-aware matching)."""

from dataclasses import dataclass

from amap_api.graph_store import GraphStore
from amap_contracts import search_key
from amap_contracts.graph import NodeKind


@dataclass(frozen=True, slots=True)
class Place:
    id: str  # node id of the representative panorama
    name_tr: str
    name_en: str
    kind: NodeKind
    building: str | None
    node_ids: tuple[str, ...]
    key: str


def build_places(store: GraphStore) -> list[Place]:
    """Group panoramas by label; entrances represent their building."""
    groups: dict[str, list[str]] = {}
    for node in store.graph.nodes:
        groups.setdefault(node.label.tr, []).append(node.id)
    places: list[Place] = []
    for label, node_ids in sorted(groups.items()):
        first = store.nodes[sorted(node_ids)[0]]
        places.append(
            Place(
                id=first.id,
                name_tr=label,
                name_en=first.label.en,
                kind=first.kind,
                building=first.building,
                node_ids=tuple(sorted(node_ids)),
                key=search_key(f"{label} {first.label.en}"),
            )
        )
    return places


def search_places(places: list[Place], query: str, limit: int = 10) -> list[Place]:
    """Rank: exact > prefix > every query word starts a label word; entrances first."""
    q = search_key(query)
    if not q:
        return []
    words = q.split()

    def rank(place: Place) -> int | None:
        if place.key == q or search_key(place.name_tr) == q:
            return 0
        if place.key.startswith(q):
            return 1
        tokens = place.key.split()
        if all(any(t.startswith(w) for t in tokens) for w in words):
            return 2
        return None

    scored = [(r, p) for p in places if (r := rank(p)) is not None]
    scored.sort(
        key=lambda rp: (rp[0], rp[1].kind is not NodeKind.ENTRANCE, rp[1].name_tr)
    )
    return [p for _, p in scored[:limit]]
