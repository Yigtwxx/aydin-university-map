"""Documents for the assistant's knowledge base, in Turkish and English.

Sources (all derived from data we already hold):

- **spot**: one document per panorama: tour label, area, floor and building
  parsed from the label, plus the Gemini description, landmarks and signage
  when available;
- **area**: one document per tour area (a building or a part of the campus)
  listing its floors and rooms, which answers "what is in T Blok?";
- **campus**: an overview of blocks, entrances and routable places.

Every document carries metadata the assistant's tools use: scene id, the
routable graph node (if the spot is in the walking graph), building code and
floor.
"""

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# "M Blok -1.Kat" is a basement, but in "O Blok-1.K" the hyphen only joins the
# block and the floor: a minus sign must follow whitespace or start the label.
_FLOOR = re.compile(
    r"(?:^|\s)(-?\d+)\s*\.\s*(?:Kat|K\b|Floor)|-(\d+)\s*\.\s*(?:Kat|K\b|Floor)",
    re.IGNORECASE,
)
_BLOCK = re.compile(r"\b([A-Z])\s*Blok\b")
_GROUND = re.compile(r"giriş kat|zemin kat|ground floor", re.IGNORECASE)

KIND_TR = {"outdoor": "açık alan", "entrance": "giriş", "indoor": "bina içi"}
KIND_EN = {"outdoor": "open area", "entrance": "entrance", "indoor": "indoors"}


@dataclass(frozen=True, slots=True)
class Document:
    source: str  # spot | area | campus
    source_ref: str
    lang: str  # tr | en
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        payload = (
            f"{self.source}|{self.source_ref}|{self.lang}|{self.title}|{self.content}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def floor_of(*texts: str) -> int | None:
    for text in texts:
        match = _FLOOR.search(text)
        if match:
            return int(match.group(1) or match.group(2))
        if _GROUND.search(text):
            return 0
    return None


def block_of(*texts: str) -> str | None:
    for text in texts:
        match = _BLOCK.search(text)
        if match:
            return match.group(1)
    return None


def _floor_text(floor: int | None, lang: str) -> str:
    if floor is None:
        return ""
    if lang == "tr":
        return "zemin kat" if floor == 0 else f"{floor}. kat"
    return "ground floor" if floor == 0 else f"floor {floor}"


def spot_documents(
    scenes: Iterable[Mapping[str, Any]],
    vision: Mapping[str, Mapping[str, Any]],
    graph_nodes: set[str],
) -> list[Document]:
    docs: list[Document] = []
    for s in scenes:
        label, area = s["label"], s["area"]
        floor = floor_of(label["tr"], area["tr"])
        block = block_of(label["tr"], area["tr"])
        seen = vision.get(s["name"], {})
        meta = {
            "scene": s["name"],
            "kind": s["kind"],
            "area_tr": area["tr"],
            "building": block,
            "floor": floor,
            "node_id": s["name"] if s["name"] in graph_nodes else None,
        }
        for lang in ("tr", "en"):
            kind = (KIND_TR if lang == "tr" else KIND_EN)[s["kind"]]
            where = ", ".join(
                p for p in (area[lang], _floor_text(floor, lang), kind) if p
            )
            parts = [f"{label[lang]} ({where})."]
            if seen.get(f"description_{lang}"):
                parts.append(str(seen[f"description_{lang}"]))
            if seen.get("landmarks"):
                head = "Belirgin noktalar" if lang == "tr" else "Landmarks"
                parts.append(f"{head}: {', '.join(seen['landmarks'])}.")
            if seen.get("signage_text"):
                head = "Tabelalar" if lang == "tr" else "Signs"
                parts.append(f"{head}: {', '.join(seen['signage_text'])}.")
            if seen.get("accessibility"):
                head = "Erişilebilirlik" if lang == "tr" else "Accessibility"
                parts.append(f"{head}: {'; '.join(seen['accessibility'])}.")
            docs.append(
                Document("spot", s["name"], lang, label[lang], " ".join(parts), meta)
            )
    return docs


def _area_floors(area_tr: str, members: Iterable[Mapping[str, Any]]) -> list[int]:
    return sorted(
        {f for m in members if (f := floor_of(m["label"]["tr"], area_tr)) is not None}
    )


def _related_areas(
    area_tr: str,
    lang: str,
    by_area: Mapping[str, list[Mapping[str, Any]]],
) -> list[str]:
    """Other tour areas named after the block that ``area_tr`` ("T Blok") is.

    The tour splits a block into areas ("T Blok" and "T Blok Sınıflar", or
    "M Blok", "M Blok-5.K" and "Kimya - M Blok"); listing them in the block's
    own document lets one chunk answer "what is in T Blok?".
    """
    block = block_of(area_tr)
    if block is None or area_tr.strip() != f"{block} Blok":
        return []
    parts: list[str] = []
    for other, members in sorted(by_area.items()):
        if other == area_tr or block_of(other) != block:
            continue
        name = other if lang == "tr" else members[0]["area"]["en"]
        rooms = ", ".join(sorted({m["label"][lang] for m in members}))
        floors = ", ".join(_floor_text(f, lang) for f in _area_floors(other, members))
        parts.append(f"{name} ({floors}: {rooms})" if floors else f"{name} ({rooms})")
    return parts


def area_documents(scenes: Iterable[Mapping[str, Any]]) -> list[Document]:
    by_area: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for s in scenes:
        if s["area"]["tr"] and s["area"]["tr"] != "0":
            by_area[s["area"]["tr"]].append(s)
    docs: list[Document] = []
    for area_tr, members in sorted(by_area.items()):
        area_en = members[0]["area"]["en"]
        block = block_of(area_tr) or next(
            (b for m in members if (b := block_of(m["label"]["tr"]))), None
        )
        floors = _area_floors(area_tr, members)
        for lang, name in (("tr", area_tr), ("en", area_en)):
            rooms = sorted({m["label"][lang] for m in members})
            if lang == "tr":
                text = f"{name} bölümünde {len(members)} 360° nokta var."
                if floors:
                    text += (
                        f" Katlar: {', '.join(_floor_text(f, 'tr') for f in floors)}."
                    )
                text += f" Buradaki yerler: {', '.join(rooms)}."
            else:
                text = f"{name} has {len(members)} 360° spots."
                if floors:
                    text += (
                        f" Floors: {', '.join(_floor_text(f, 'en') for f in floors)}."
                    )
                text += f" Places here: {', '.join(rooms)}."
            related = _related_areas(area_tr, lang, by_area)
            if related:
                head = (
                    "Aynı bloğun turdaki diğer bölümleri"
                    if lang == "tr"
                    else "Other parts of this block in the tour"
                )
                text += f" {head}: {'; '.join(related)}."
            docs.append(
                Document(
                    "area",
                    area_tr,
                    lang,
                    name,
                    text,
                    {"area_tr": area_tr, "building": block, "floors": floors},
                )
            )
    return docs


def campus_documents(
    scenes: Iterable[Mapping[str, Any]], routable_labels: Iterable[str]
) -> list[Document]:
    scenes = list(scenes)
    blocks = sorted(
        {b for s in scenes if (b := block_of(s["label"]["tr"], s["area"]["tr"]))}
    )
    entrance_names = {
        s["label"]["tr"]: s["label"]["en"] for s in scenes if s["kind"] == "entrance"
    }
    entrances = sorted(entrance_names)
    # Since indoor routing every spot is routable (400+ labels): listing them
    # all split this overview into six chunks. The count and the routable
    # entrances say the same in one; rooms are found with the place search.
    routable = set(routable_labels)
    gates = [e for e in entrances if e in routable]
    tr = (
        "İstanbul Aydın Üniversitesi Florya Halit Aydın Yerleşkesi, İstanbul'un "
        "Küçükçekmece ilçesinde, Florya'da, eski Atatürk Havalimanı'nın yanındadır. "
        f"Turda geçen bloklar: {', '.join(b + ' Blok' for b in blocks)}. "
        f"Girişler: {', '.join(entrances)}. "
        f"Haritada şu an {len(routable)} yere yürüyüş rotası çizilebiliyor "
        "(binaların içindeki odalar dahil); rota çizilebilen girişler: "
        f"{', '.join(gates)}."
    )
    en = (
        "İstanbul Aydın University's Florya Halit Aydın Campus is in Florya, "
        "Küçükçekmece, İstanbul, next to the former Atatürk Airport. "
        f"Blocks in the tour: {', '.join('Block ' + b for b in blocks)}. "
        f"Entrances: {', '.join(entrance_names[e] for e in entrances)}. "
        f"The map can route to {len(routable)} places right now (rooms inside "
        "buildings included); entrances it can route to: "
        f"{', '.join(entrance_names[e] for e in gates)}."
    )
    return [
        Document("campus", "florya", "tr", "Florya Yerleşkesi", tr, {"blocks": blocks}),
        Document("campus", "florya", "en", "Florya Campus", en, {"blocks": blocks}),
    ]
