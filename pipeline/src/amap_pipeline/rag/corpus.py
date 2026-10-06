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
        floors = sorted(
            {
                f
                for m in members
                if (f := floor_of(m["label"]["tr"], area_tr)) is not None
            }
        )
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
    entrances = sorted({s["label"]["tr"] for s in scenes if s["kind"] == "entrance"})
    routable = sorted(set(routable_labels))
    tr = (
        "İstanbul Aydın Üniversitesi Florya Halit Aydın Yerleşkesi, İstanbul'un "
        "Küçükçekmece ilçesinde, Florya'da, eski Atatürk Havalimanı'nın yanındadır. "
        f"Turda geçen bloklar: {', '.join(b + ' Blok' for b in blocks)}. "
        f"Girişler: {', '.join(entrances)}. "
        f"Haritada şu an yürüyüş rotası çizilebilen yerler: {', '.join(routable)}."
    )
    en = (
        "İstanbul Aydın University's Florya Halit Aydın Campus is in Florya, "
        "Küçükçekmece, İstanbul, next to the former Atatürk Airport. "
        f"Blocks in the tour: {', '.join('Block ' + b for b in blocks)}. "
        f"Entrances: {', '.join(entrances)}. "
        f"Places the map can route to right now: {', '.join(routable)}."
    )
    return [
        Document("campus", "florya", "tr", "Florya Yerleşkesi", tr, {"blocks": blocks}),
        Document("campus", "florya", "en", "Florya Campus", en, {"blocks": blocks}),
    ]
