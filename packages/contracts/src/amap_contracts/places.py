"""Searchable places derived from panorama labels (Turkish-aware matching).

Shared by the API (in-memory search) and the pipeline (database loader), so
both rank and group places the same way.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from amap_contracts.graph import Node, NodeKind
from amap_contracts.text import search_key


@dataclass(frozen=True, slots=True)
class Place:
    id: str  # node id of the representative panorama
    name_tr: str
    name_en: str
    kind: NodeKind
    building: str | None
    node_ids: tuple[str, ...]
    key: str


def build_places(nodes: Iterable[Node]) -> list[Place]:
    """Group panoramas by label; entrances represent their building."""
    by_id = {node.id: node for node in nodes}
    groups: dict[str, list[str]] = {}
    for node in by_id.values():
        groups.setdefault(node.label.tr, []).append(node.id)
    places: list[Place] = []
    for label, node_ids in sorted(groups.items()):
        first = by_id[sorted(node_ids)[0]]
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


def _word_matches(word: str, tokens: list[str]) -> bool:
    # A single letter is a block code ("b blok"): it must be a whole token, or
    # it would match "blok", "block" and "entrance" of every other block.
    if len(word) == 1:
        return word in tokens
    return any(token.startswith(word) for token in tokens)


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
        if all(_word_matches(w, tokens) for w in words):
            return 2
        return None

    scored = [(r, p) for p in places if (r := rank(p)) is not None]
    scored.sort(
        key=lambda rp: (rp[0], rp[1].kind is not NodeKind.ENTRANCE, rp[1].name_tr)
    )
    return [p for _, p in scored[:limit]]
