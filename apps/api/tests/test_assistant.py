"""Campus assistant with the offline model (no network, no API keys)."""

import asyncio
from collections.abc import Iterator, Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from amap_api.assistant.agent import (
    KNOWLEDGE_DOWN,
    SUGGESTIONS,
    AssistantDeps,
    _resolve,  # pyright: ignore[reportPrivateUsage]
    _suggestions,  # pyright: ignore[reportPrivateUsage]
    build_agent,
    describe,
    keep_recent,
)
from amap_api.assistant.knowledge import Knowledge, diversify
from amap_api.db import Database
from amap_api.graph_store import GraphStore
from amap_api.main import CHAT_BUCKET, create_app
from amap_api.places import Place, build_places
from amap_api.rate_limit import TokenBucket
from amap_api.settings import Settings
from amap_contracts.graph import LocalizedText, NodeKind
from amap_contracts.pois import Poi, PoiCategory


@pytest.fixture
def chat_client(store: GraphStore) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        graph_source="unused",
        amap_assistant_model="offline",
    )
    CHAT_BUCKET._tokens.clear()  # pyright: ignore[reportPrivateUsage]
    with TestClient(create_app(settings=settings, store=store)) as client:
        yield client


def _ask(text: str) -> dict[str, object]:
    return {
        "trigger": "submit-message",
        "id": "chat-1",
        "messages": [
            {"id": "m1", "role": "user", "parts": [{"type": "text", "text": text}]}
        ],
    }


def test_chat_streams_route_tool_call_and_answer(chat_client: TestClient) -> None:
    response = chat_client.post("/chat", json=_ask("A blok nerede?"))
    body = response.text
    assert response.status_code == 200, body
    assert '"toolName":"get_route"' in body, "route tool call must stream"
    assert '"node_ids":["a","b","c"]' in body, "tool output carries the route"
    assert '"delta":"Rotayı ' in body, "final answer streams word by word"


def test_chat_rejects_long_questions(chat_client: TestClient) -> None:
    response = chat_client.post("/chat", json=_ask("x" * 1001))
    assert response.status_code == 413, response.text


def test_chat_without_models_is_unavailable(client: TestClient) -> None:
    assert client.post("/chat", json=_ask("merhaba")).status_code == 503


def test_token_bucket_blocks_bursts_then_refills() -> None:
    bucket = TokenBucket(capacity=2, refill_per_s=1.0)
    assert bucket.allow("ip", now=0.0) and bucket.allow("ip", now=0.0)
    assert not bucket.allow("ip", now=0.0), "third request in a burst is blocked"
    assert bucket.allow("ip", now=1.0), "one token is back after a second"


def test_keep_recent_starts_at_a_user_turn() -> None:
    def turn(i: int) -> list[object]:
        return [
            ModelRequest(parts=[UserPromptPart(content=f"q{i}")]),
            ModelResponse(parts=[ToolCallPart("get_route", {"to_place": "x"})]),
            ModelRequest(parts=[ToolReturnPart("get_route", {}, tool_call_id="t")]),
            ModelResponse(parts=[TextPart(f"a{i}")]),
        ]

    history = [m for i in range(4) for m in turn(i)]
    kept = keep_recent(history)  # pyright: ignore[reportArgumentType]
    first = kept[0]
    assert isinstance(first, ModelRequest), "history must start with a request"
    assert isinstance(first.parts[0], UserPromptPart), "...that is a user prompt"
    assert len(kept) <= 8, f"kept {len(kept)} messages"


def test_keep_recent_long_turn_keeps_the_question() -> None:
    # Eval regression (Step 4.4): after four tool rounds the old trimming sent
    # only the last tool result, and the model answered with a greeting.
    question = ModelRequest(parts=[UserPromptPart(content="T Blok'a nasıl giderim?")])
    rounds: list[ModelMessage] = []
    for i in range(4):
        call = ToolCallPart("search_places", {}, tool_call_id=f"t{i}")
        result = ToolReturnPart("search_places", [], tool_call_id=f"t{i}")
        rounds += [ModelResponse(parts=[call]), ModelRequest(parts=[result])]
    history: list[ModelMessage] = [question, *rounds]
    assert len(history) > 8, f"the turn must exceed the budget, got {len(history)}"
    kept = keep_recent(history)
    assert kept == history, f"the current turn must be sent whole, kept {len(kept)}"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("A Blok'a", "c"),  # apostrophe suffix
        ("Kütüphane Girişi", "d"),  # possessive suffix on "Giriş"
        ("Kütüphane", "d"),
        ("T Blok", None),  # not in the walking graph
        ("Girişinden", None),  # fits "A Blok Girişi" and "Kütüphane Giriş"
    ],
)
def test_resolve_turkish_suffixes_find_the_place(
    store: GraphStore, name: str, expected: str | None
) -> None:
    deps = AssistantDeps(store=store, places=build_places(store), knowledge=None)
    place = _resolve(deps, name)
    found = place.id if place else None
    assert found == expected, f"{name!r}: expected {expected}, got {found}"


class _QuotaExhaustedKnowledge(Knowledge):
    """Every search fails, like a spent free-tier embedding quota (HTTP 429)."""

    def __init__(self) -> None:  # no database, no Gemini client
        pass

    async def search(
        self, question: str, lang: str, k: int = 5
    ) -> list[dict[str, Any]]:
        raise RuntimeError("429 RESOURCE_EXHAUSTED")


def _call_tool(
    store: GraphStore,
    tool: str,
    args: dict[str, Any],
    knowledge: Knowledge | None = None,
    pois: Sequence[Poi] = (),
) -> tuple[Any, str]:
    """Run one tool call through the real agent: (tool result, final answer)."""

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        if isinstance(last, ModelRequest) and any(
            isinstance(p, ToolReturnPart) for p in last.parts
        ):
            return ModelResponse(parts=[TextPart("Tamam.")])
        return ModelResponse(parts=[ToolCallPart(tool, args)])

    places = build_places(store, pois)
    deps = AssistantDeps(store=store, places=places, knowledge=knowledge)
    result = asyncio.run(build_agent(FunctionModel(respond)).run("?", deps=deps))
    returned = [
        p.content
        for m in result.all_messages()
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, ToolReturnPart)
    ]
    assert len(returned) == 1, f"expected one tool result, got {returned}"
    return returned[0], result.output


def test_search_knowledge_quota_error_returns_tool_error(store: GraphStore) -> None:
    args = {"query": "T Blok", "lang": "tr"}
    output, answer = _call_tool(
        store, "search_knowledge", args, knowledge=_QuotaExhaustedKnowledge()
    )
    assert output == [{"error": KNOWLEDGE_DOWN}], f"got {output}"
    assert answer, "the chat still answers instead of failing"


def test_get_route_to_room_enters_and_climbs(indoor_store: GraphStore) -> None:
    output, _ = _call_tool(indoor_store, "get_route", {"to_place": "Anatomi Lab"})
    assert output["to"]["floor"] == -1, f"room floor: {output['to']}"
    assert output["approximate"] is True, "indoor lengths are estimates"
    steps = output["steps_tr"]
    assert "M Blok'a girin" in steps, f"enters the block: {steps}"
    assert any(s.startswith("Merdivenle 1 kat inin") for s in steps), steps
    assert steps[-1] == "Vardınız: Anatomi Lab (M Blok, \u22121. kat)", steps[-1]


def test_get_route_same_named_rooms_asks_with_floors(indoor_store: GraphStore) -> None:
    output, _ = _call_tool(indoor_store, "get_route", {"to_place": "Derslik"})
    options = {(o["building"], o["floor"]) for o in output.get("did_you_mean", [])}
    assert "error" in output, f"two classrooms must not be guessed: {output}"
    assert options == {("D", 3), ("M", 5)}, f"both rooms with floors, got {options}"


def test_get_route_block_named_room_resolves(indoor_store: GraphStore) -> None:
    output, _ = _call_tool(indoor_store, "get_route", {"to_place": "Derslik D Blok"})
    assert output.get("to", {}).get("id") == "class_d", f"got {output}"


def test_get_route_unknown_place_lists_entrances_only(
    indoor_store: GraphStore,
) -> None:
    output, _ = _call_tool(indoor_store, "get_route", {"to_place": "Rektörlük"})
    expected = ["D Blok Giriş", "M Blok Giriş", "M Blok Yan Giriş"]
    assert output.get("entrances") == expected, f"entrances only, got {output}"


# Like configs/pois.toml: the canteen enriches a tour spot that has no block
# or floor of its own (scene_428757 "Kantin"; here the "Geçit" passage).
CANTEEN = Poi(
    id="t-blok-yemekhane",
    name=LocalizedText(
        tr="Yemekhane ve Kantin (T Blok)", en="Dining Hall and Canteen (T Block)"
    ),
    category=PoiCategory.FOOD,
    aliases=("yemekhane", "kantin", "t blok kantin", "refectory"),
    node_id="p",
    building="T",
    floor=4,
)


@pytest.mark.parametrize(
    "query",
    [
        "Yemekhane",
        # Production bug: whole questions and inflected names found nothing,
        # and the assistant said it had no information about the canteen.
        "yemekhane hangi katta",
        "Yemekhane kaçıncı kat",  # "kat" alone would rank corridors first
        "yemekhanenin katı",
    ],
)
def test_search_places_finds_the_canteen_with_its_floor(
    indoor_store: GraphStore, query: str
) -> None:
    output, _ = _call_tool(
        indoor_store, "search_places", {"query": query}, pois=[CANTEEN]
    )
    assert output, f"{query!r}: the canteen must be found, got {output}"
    first = output[0]
    assert first["name_tr"] == "Yemekhane ve Kantin (T Blok)", f"{query!r}: {output}"
    got = (first["building"], first["floor"], first.get("category"))
    assert got == ("T", 4, "food"), f"{query!r}: block, floor, category: {first}"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # Strict matches are returned as before: the tolerant search would
        # add the other "Derslik" (M Blok), sharing one word of three.
        ("Derslik D Blok", ["class_d"]),
        ("Derslik", ["class_d", "class_m"]),
        ("Rektörlük", []),  # nothing in common: still an empty list
        ("hangi katta", []),  # question words only
    ],
)
def test_search_places_strict_matches_are_unchanged(
    indoor_store: GraphStore, query: str, expected: list[str]
) -> None:
    output, _ = _call_tool(
        indoor_store, "search_places", {"query": query}, pois=[CANTEEN]
    )
    ids = [place["id"] for place in output]
    assert ids == expected, f"{query!r}: expected {expected}, got {ids}"
    assert all("category" not in place for place in output), "rooms have none"


def test_suggestions_stay_small_on_a_large_campus() -> None:
    # 200+ places since indoor routing: the error must not list them all
    # (Groq's free tier allows 8K tokens a minute).
    rooms = [
        Place(f"r{i}", "Derslik", "Classroom", NodeKind.INDOOR, f"B{i}", (f"r{i}",),
              key=f"derslik classroom b{i} blok", floor=i % 6)
        for i in range(200)
    ]  # fmt: skip
    found = _suggestions(rooms, "Derslik")
    assert len(found) == SUGGESTIONS, f"capped at {SUGGESTIONS}, got {len(found)}"


class _CountingEmbeddings:
    def __init__(self) -> None:
        self.calls = 0

    async def embed_content(self, **_kwargs: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.5, 0.25])])


def test_knowledge_repeated_question_embeds_once(fake_db: Database) -> None:
    knowledge = Knowledge(fake_db, gemini_api_key="test-key")
    fake = _CountingEmbeddings()
    knowledge.client = SimpleNamespace(aio=SimpleNamespace(models=fake))  # pyright: ignore[reportAttributeAccessIssue]
    # Whitespace and case variants share one cached (float32) vector.
    for question in ["T Blok", "  T   Blok ", "t blok"]:
        vector = asyncio.run(knowledge.embed_query(question))
        assert vector == [0.5, 0.25], f"{question!r}: got {vector}"
    assert fake.calls == 1, f"expected one embedding call, got {fake.calls}"


def test_diversify_near_duplicate_spots_leave_room_for_others() -> None:
    def row(title: str, area: str | None) -> dict[str, Any]:
        return {"title": title, "metadata": {"area_tr": area}}

    garden = [row("T Blok Bahçe", "T Blok") for _ in range(4)]
    rows = [row("T Blok Giriş", "T Blok"), *garden, row("T Blok", "T Blok")]
    kept = diversify(rows, k=5)
    titles = [r["title"] for r in kept]
    assert titles.count("T Blok Bahçe") == 2, f"capped at two, got {titles}"
    assert "T Blok" in titles, f"the block document gets a slot, got {titles}"
    assert len(kept) == 4, f"six rows, two capped: expected 4, got {len(kept)}"


M = "\u2212"  # floors are written with U+2212 MINUS SIGN ("\u22121. kat")


def _library() -> list[Place]:
    """Library spots as the tour labels them: "Kütüphane -3.Kat" to "3.Kat"."""
    floors = [
        Place(
            f"k{f}",
            f"Kütüphane {f}.Kat",
            f"Library Floor {f}",
            NodeKind.INDOOR,
            "T",
            (f"k{f}",),
            key=f"kutuphane {f} kat library floor {f} t blok",
            floor=f,
            area_tr="Kütüphane",
            area_en="Library",
        )
        for f in range(-3, 4)
    ]
    entrance = Place(
        "kg",
        "Kütüphane Giriş",
        "Library Entrance",
        NodeKind.ENTRANCE,
        None,
        ("kg",),
        key="kutuphane giris library entrance",
        area_tr="Kütüphane",
        area_en="Library",
    )
    return [*floors, entrance]  # fmt: skip


@pytest.mark.parametrize(
    ("name", "lang", "first", "last"),
    [
        ("Kütüphane", "tr", f"{M}3. kat", "3. kat"),
        ("library", "en", f"floor {M}3", "floor 3"),
        ("library floors", "en", f"floor {M}3", "floor 3"),  # question words
    ],
)
def test_describe_library_counts_its_floors(
    name: str, lang: str, first: str, last: str
) -> None:
    # QA (Step 4.4): "How many floors does the library have?" got "I don't
    # have that information" although the tour has floors -3 to 3.
    out = describe(_library(), name, lang)
    floors = out["floors_in_tour"]
    assert out["floor_count_in_tour"] == 7, f"{name!r}: got {floors}"
    assert (floors[0], floors[-1]) == (first, last), f"{name!r}: got {floors}"
    assert out["entrances"], f"the entrance is listed: {out}"


def test_describe_block_lists_rooms_by_floor(indoor_store: GraphStore) -> None:
    out = describe(build_places(indoor_store), "M Blok", "tr")
    assert out["floors_in_tour"] == [f"{M}1. kat", "5. kat"], out["floors_in_tour"]
    by_floor = {f["floor"]: f["rooms"] for f in out["rooms_by_floor"]}
    assert "Anatomi Lab" in by_floor[f"{M}1. kat"], f"got {by_floor}"
    assert out["entrances"] == ["M Blok Giriş", "M Blok Yan Giriş"], out


def test_describe_unknown_name_lists_blocks(indoor_store: GraphStore) -> None:
    out = describe(build_places(indoor_store), "Rektörlük", "tr")
    assert "error" in out and out["blocks"] == ["D", "M"], f"got {out}"


def test_describe_place_tool_answers_in_english(indoor_store: GraphStore) -> None:
    args = {"name": "M Block", "lang": "en"}
    output, _ = _call_tool(indoor_store, "describe_place", args)
    floors = output["floors_in_tour"]
    assert floors == [f"floor {M}1", "floor 5"], f"got {floors}"
