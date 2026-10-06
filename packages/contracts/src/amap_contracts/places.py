"""Searchable places derived from panorama labels (Turkish-aware matching).

Shared by the API (in-memory search) and the pipeline (database loader), so
both rank and group places the same way.

Outdoors a place is every panorama sharing a label (entrances represent their
building). Indoors the same label names different rooms in different blocks
("Derslik"), so rooms are grouped by label, block and floor, and their search
key also holds the block and the area ("Kimya - M Blok").
"""

from collections.abc import Iterable
from dataclasses import dataclass

from amap_contracts.graph import Node, NodeKind
from amap_contracts.text import search_key

# Areas that say nothing about where a room is.
_GENERIC_AREAS = frozenset({"", "0", "florya kampus", "kampus", "florya campus"})


def is_generic_area(area: str) -> bool:
    """True for tour areas that name the campus at large, not a building."""
    return search_key(area) in _GENERIC_AREAS


# Search ties: entrances, then open areas, then rooms.
_KIND_ORDER = {NodeKind.ENTRANCE: 0, NodeKind.OUTDOOR: 1, NodeKind.INDOOR: 2}


@dataclass(frozen=True, slots=True)
class Place:
    id: str  # node id of the representative panorama
    name_tr: str
    name_en: str
    kind: NodeKind
    building: str | None
    node_ids: tuple[str, ...]
    key: str
    floor: int | None = None
    area_tr: str = ""
    area_en: str = ""


def _room_key(node: Node) -> str:
    parts = [node.label.tr, node.label.en]
    if node.building:
        parts += [f"{node.building} blok", f"{node.building} block"]
    parts += [a for a in (node.area.tr, node.area.en) if not is_generic_area(a)]
    return search_key(" ".join(parts))


def build_places(nodes: Iterable[Node]) -> list[Place]:
    """Group panoramas into places; entrances represent their building."""
    by_id = {node.id: node for node in nodes}
    groups: dict[tuple[str, str], list[str]] = {}
    for node in by_id.values():
        scope = (
            f"{node.building or ''}|{'' if node.floor is None else node.floor}"
            if node.kind is NodeKind.INDOOR
            else ""
        )
        groups.setdefault((node.label.tr, scope), []).append(node.id)
    places: list[Place] = []
    for (label, scope), node_ids in sorted(groups.items()):
        ordered = sorted(node_ids)
        # A measured panorama represents the place where there is one: routes
        # to it end where the map can draw them.
        first = by_id[
            next((i for i in ordered if not by_id[i].approximate), ordered[0])
        ]
        room = scope != ""
        places.append(
            Place(
                id=first.id,
                name_tr=label,
                name_en=first.label.en,
                kind=first.kind,
                building=first.building,
                node_ids=tuple(ordered),
                key=_room_key(first)
                if room
                else search_key(f"{label} {first.label.en}"),
                floor=first.floor if room else None,
                area_tr=first.area.tr,
                area_en=first.area.en,
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
    """Rank: exact > prefix > every query word starts a word; entrances first.

    Among word matches, more words found in the name itself come first: a
    room's key also holds its block and area, and "sınıf 2 t blok" means
    "Sınıf - 2", not "Amfi - 2" in the area "T Blok Sınıflar".
    """
    q = search_key(query)
    if not q:
        return []
    words = q.split()

    def rank(place: Place) -> tuple[int, int] | None:
        if place.key == q or search_key(place.name_tr) == q:
            return (0, 0)
        if place.key.startswith(q):
            return (1, 0)
        tokens = place.key.split()
        if all(_word_matches(w, tokens) for w in words):
            name = search_key(f"{place.name_tr} {place.name_en}").split()
            return (2, -sum(_word_matches(w, name) for w in words))
        return None

    scored = [(r, p) for p in places if (r := rank(p)) is not None]
    scored.sort(
        key=lambda rp: (
            rp[0],
            _KIND_ORDER.get(rp[1].kind, 3),
            rp[1].name_tr,
            rp[1].building or "",
            -999 if rp[1].floor is None else rp[1].floor,
        )
    )
    return [p for _, p in scored[:limit]]
