"""Knowledge-base documents built from synthetic scenes (no tour data)."""

import pytest

from amap_pipeline.rag.corpus import (
    Document,
    area_documents,
    block_of,
    floor_of,
    spot_documents,
)
from amap_pipeline.rag.embed import document_text, query_text
from amap_pipeline.rag.load import MAX_CHUNK_CHARS, split_long, vector_literal


def _scene(name: str, tr: str, en: str, area: str, kind: str = "indoor") -> dict:
    return {
        "name": name,
        "kind": kind,
        "label": {"tr": tr, "en": en},
        "area": {"tr": area, "en": area.replace("Blok", "Block")},
    }


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (("T Blok 2.Kat",), 2),
        (("M Blok -1.Kat",), -1),
        (("Gastronomi - O Blok-1.K",), 1),
        (("Kafe - Giriş Kat",), 0),
        (("Derslik",), None),
    ],
)
def test_floor_of_reads_turkish_floor_labels(
    texts: tuple[str, ...], expected: int | None
) -> None:
    assert floor_of(*texts) == expected, f"{texts} -> {floor_of(*texts)}"


def test_block_of_finds_the_block_letter() -> None:
    assert block_of("Derslik", "Kimya - M Blok") == "M", "letter from the area"
    assert block_of("Kafe") is None, "no block in the label"


def test_spot_documents_merge_vision_and_mark_routable_nodes() -> None:
    scenes = [_scene("s1", "A Blok Girişi", "A Block Entrance", "A Blok", "entrance")]
    vision = {"s1": {"description_tr": "Sarı cephe.", "landmarks": ["bayrak"]}}
    docs = spot_documents(scenes, vision, graph_nodes={"s1"})
    tr = next(d for d in docs if d.lang == "tr")
    assert "Sarı cephe." in tr.content and "bayrak" in tr.content, tr.content
    assert tr.metadata["node_id"] == "s1", "spot in the graph is routable"
    assert tr.metadata["building"] == "A", tr.metadata
    assert {d.lang for d in docs} == {"tr", "en"}, "one document per language"


def test_area_documents_list_floors_and_rooms() -> None:
    scenes = [
        _scene("s1", "T Blok 1.Kat", "T Block 1.Floor", "T Blok"),
        _scene("s2", "T Blok 3.Kat", "T Block 3.Floor", "T Blok"),
    ]
    tr = next(d for d in area_documents(scenes) if d.lang == "tr")
    assert "1. kat, 3. kat" in tr.content, tr.content
    assert tr.metadata["floors"] == [1, 3], tr.metadata


def test_split_long_keeps_short_documents_whole() -> None:
    doc = Document("area", "x", "tr", "X", "Kısa. Metin.")
    assert split_long(doc) == [doc], "short documents are not split"


def test_split_long_cuts_at_sentence_ends() -> None:
    sentence = "Bu bir cümle " + "x" * 90
    doc = Document("area", "x", "tr", "X", ". ".join([sentence] * 40))
    pieces = split_long(doc)
    assert len(pieces) > 1, "a long document is split"
    assert all(len(p.content) <= MAX_CHUNK_CHARS for p in pieces), "pieces fit"
    assert len({p.content_hash for p in pieces}) == len(pieces), "unique hashes"


def test_embedding_prefixes_and_vector_literal() -> None:
    assert document_text("A", "b") == "title: A | text: b"
    assert query_text("nerede?") == "task: search result | query: nerede?"
    assert vector_literal([0.1, -0.25]) == "[0.100000,-0.250000]"
