"""The campus assistant agent (pydantic-ai) and its tools.

Models: Groq ``openai/gpt-oss-120b`` first, then the smaller ``gpt-oss-20b``
and Gemini Flash-Lite when a model is rate-limited or down (free tiers). The
history is trimmed to the last few turns before each request: Groq's free
tier allows 8K tokens per minute.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic_ai import Agent, ModelSettings, RunContext, UsageLimits
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import Model

from amap_api.assistant.knowledge import Knowledge
from amap_api.directions import floor_en, floor_tr, instruction
from amap_api.graph_store import GraphStore
from amap_api.routing import NoRouteError, shortest_route
from amap_contracts.graph import NodeKind
from amap_contracts.places import Place, is_generic_area, search_places
from amap_contracts.text import search_key

log = logging.getLogger("amap_api.assistant")

PROMPT_PATH = Path(__file__).parent / "prompts" / "assistant_v4.md"
PROMPT = PROMPT_PATH.read_text("utf-8")
DEFAULT_START = "Kampüs Girişi"
KEEP_MESSAGES = 8
# The longest knowledge chunk has 1,024 characters: the old 600-character cut
# lost the accessibility notes (steps, ramps) at the end of 23 descriptions.
MAX_CHUNK_CHARS = 1200
KNOWLEDGE_DOWN = "knowledge search is unavailable right now"
SUGGESTIONS = 8  # places offered when a name does not resolve
SEARCH_RESULTS = 5  # places in one search_places result
MAX_DESCRIBE_ROOMS = 40  # room names in one describe_place result
# Question words that name no area ("library floors" means "library").
_DESCRIBE_STOPWORDS = frozenset(
    {"kat", "katlari", "katli", "kac", "floor", "floors", "how", "many", "the"}
)
# Question words that name no place, dropped before the tolerant search:
# "yemekhane kaçıncı kat" means "yemekhane", and "kat" alone would rank every
# "... Kat" corridor of the tour above it.
_QUESTION_WORDS = _DESCRIBE_STOPWORDS | frozenset(
    {
        "hangi", "kacinci", "kacta", "katta", "kati", "katinda", "nerede",
        "nerde", "neresi", "nasil", "ne", "mi", "mu", "ve", "saat", "acik",
        "aciliyor", "kapaniyor", "where", "which", "what", "is", "on", "and",
        "open", "opens", "close", "closes", "time", "hours",
    }
)  # fmt: skip
# Ties in suggestions: entrances, then open areas, then rooms.
_KIND_ORDER = {NodeKind.ENTRANCE: 0, NodeKind.OUTDOOR: 1, NodeKind.INDOOR: 2}
# Straight or typographic apostrophe (U+2019) and the suffix after it.
_APOSTROPHE_SUFFIX = re.compile(r"['\u2019]\w*")

MODEL_SETTINGS = ModelSettings(max_tokens=700, temperature=0.3)
USAGE_LIMITS = UsageLimits(request_limit=5, total_tokens_limit=24_000)


@dataclass(slots=True)
class AssistantDeps:
    store: GraphStore
    places: list[Place]
    knowledge: Knowledge | None
    lang: Literal["tr", "en"] = "tr"  # the visitor's interface language


def keep_recent(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Whole recent turns, at most ``KEEP_MESSAGES`` messages when they fit.

    The current turn is always kept whole, however many tool calls it made:
    cutting inside it would drop the visitor's question (after four tool
    rounds the model then saw only a tool result and answered with a
    greeting). Starting at a user turn also keeps tool calls paired.
    """
    if len(messages) <= KEEP_MESSAGES:
        return messages
    starts = [
        i
        for i, message in enumerate(messages)
        if isinstance(message, ModelRequest)
        and any(isinstance(part, UserPromptPart) for part in message.parts)
    ]
    if not starts:
        return messages
    fitting = [i for i in starts if len(messages) - i <= KEEP_MESSAGES]
    return messages[fitting[0] if fitting else starts[-1] :]


def build_model(groq_api_key: str, gemini_api_key: str) -> Model:
    from pydantic_ai.models.fallback import FallbackModel
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.models.groq import GroqModel
    from pydantic_ai.providers.google import GoogleProvider
    from pydantic_ai.providers.groq import GroqProvider

    models: list[Model] = []
    if groq_api_key:
        groq = GroqProvider(api_key=groq_api_key)
        models += [
            GroqModel("openai/gpt-oss-120b", provider=groq),
            GroqModel("openai/gpt-oss-20b", provider=groq),
        ]
    if gemini_api_key:
        models.append(
            GoogleModel(
                "gemini-3.5-flash-lite", provider=GoogleProvider(api_key=gemini_api_key)
            )
        )
    if not models:
        raise ValueError("the assistant needs GROQ_API_KEY or GEMINI_API_KEY")
    return models[0] if len(models) == 1 else FallbackModel(*models)


def _place_summary(place: Place) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": place.id,
        "name_tr": place.name_tr,
        "name_en": place.name_en,
        "kind": place.kind.value,
        "building": place.building,
        "floor": place.floor,  # rooms, businesses and services
    }
    # Businesses and services (a PoiCategory value): "food" tells the model
    # that "Yemekhane ve Kantin (T Blok)" is where the visitor eats.
    if place.category is not None:
        summary["category"] = place.category
    # The tour area tells same-named rooms apart ("Mescid" in the dormitory
    # or in E Blok); "Florya Kampüs" says nothing and is left out.
    if place.area_tr and not is_generic_area(place.area_tr):
        summary["area_tr"], summary["area_en"] = place.area_tr, place.area_en
    return summary


def _query_words(name: str) -> list[str]:
    return search_key(_APOSTROPHE_SUFFIX.sub("", name)).split()


def _word_hits(word: str, tokens: list[str]) -> bool:
    if len(word) < 4:
        return word in tokens
    return any(
        t.startswith(word) or (len(t) >= 4 and word.startswith(t)) for t in tokens
    )


def _suffix_match(places: list[Place], name: str) -> Place | None:
    """Tolerates Turkish suffixes: "Kütüphane Girişi" finds "Kütüphane Giriş".

    Suffixes after an apostrophe ("E Blok'a") are dropped. Every word of four
    or more letters must start a label word or extend one (also four letters
    or more); shorter words must be whole label words. Only a single match
    counts: "Kampüs Girişinden" fits both "Kampüs Girişi" and "Kampüs - Revir
    Giriş", and guessing would draw a wrong route. Ambiguous names return
    None, so the model gets the list of routable places and picks one.
    """
    words = _query_words(name)
    found = [
        p for p in places if words and all(_word_hits(w, p.key.split()) for w in words)
    ]
    return found[0] if len(found) == 1 else None


def _suggestions(places: list[Place], name: str) -> list[Place]:
    """At most SUGGESTIONS places sharing the most words with ``name``.

    With indoor routing the campus has 200+ places: listing them all in a tool
    result would take 3K of Groq's 8K tokens a minute.
    """
    words = _query_words(name)
    scored: list[tuple[int, int, str, str, int, Place]] = []
    for p in places:
        hits = sum(_word_hits(w, p.key.split()) for w in words)
        if hits:
            order = _KIND_ORDER.get(p.kind, 3)
            floor = -999 if p.floor is None else p.floor
            scored.append((-hits, order, p.name_tr, p.building or "", floor, p))
    scored.sort(key=lambda item: item[:5])
    # Places that contain every word ("Öğrenci İşleri" in F and T Blok) beat
    # places that share one word ("Kız Öğrenci Yurdu" rooms).
    full = [item for item in scored if -item[0] == len(words)]
    return [item[-1] for item in (full or scored)[:SUGGESTIONS]]


def find_places(places: list[Place], query: str) -> list[Place]:
    """Places for ``search_places``: strict matches, else close ones.

    The strict search wants every query word in a name, but models pass whole
    questions ("yemekhane hangi katta") or inflected names ("yemekhanenin"),
    and an empty result made the assistant say it knew nothing about the
    canteen. Then question words are dropped and Turkish suffixes tolerated,
    as for route names; places known to be closed stay out.
    """
    found = search_places(places, query, SEARCH_RESULTS)
    if found:
        return found
    words = [w for w in _query_words(query) if w not in _QUESTION_WORDS]
    if not words:
        return []
    open_places = [p for p in places if not p.closed]
    return _suggestions(open_places, " ".join(words))[:SEARCH_RESULTS]


def _unresolved(deps: AssistantDeps, name: str) -> dict[str, Any]:
    options = _suggestions(deps.places, name)
    if options:
        return {
            "error": f"no single routable place matches {name!r}",
            "did_you_mean": [_place_summary(p) for p in options],
        }
    # Nothing in common: the building entrances (a few dozen names) at most.
    entrances = sorted({p.name_tr for p in deps.places if p.kind is NodeKind.ENTRANCE})
    return {"error": f"no routable place matches {name!r}", "entrances": entrances}


def _resolve(deps: AssistantDeps, name: str) -> Place | None:
    by_id = {p.id: p for p in deps.places}
    if name in by_id:
        return by_id[name]
    found = search_places(deps.places, name, limit=10)
    if found:
        best = found[0]
        same = sum(p.name_tr == best.name_tr for p in found)
        if best.kind is NodeKind.INDOOR and same > 1:
            # "Derslik" is a room in seven blocks: ask, do not guess one.
            return None
        return best
    lenient = _suffix_match(deps.places, name)
    if lenient is not None:
        return lenient
    if name == DEFAULT_START:
        # Graphs without the main gate (tests, partial runs): any open area.
        return next((p for p in deps.places if p.kind is NodeKind.OUTDOOR), None)
    return None


def _block_code(query: str) -> str | None:
    """ "T Blok", "t bloğu", "M Block", "Block M" -> the block letter."""
    words = search_key(_APOSTROPHE_SUFFIX.sub("", query)).split()
    if len(words) == 2:
        letter, word = words if len(words[0]) == 1 else reversed(words)
        if len(letter) == 1 and word.startswith("blo"):
            return letter.upper()
    return None


def _in_block(place: Place, code: str) -> bool:
    return place.building is not None and code in place.building.split("-")


def describe(places: list[Place], query: str, lang: str) -> dict[str, Any]:
    """Floors, rooms by floor and entrances of a block or a tour area.

    Built from the walking graph's tour labels, the same data routes use, so
    "how many floors does the library have?" never depends on retrieval.
    """
    code = _block_code(query)
    if code is not None:
        chosen = [p for p in places if _in_block(p, code)]
    else:
        words = [w for w in _query_words(query) if w not in _DESCRIBE_STOPWORDS]

        def area_hits(place: Place) -> bool:
            area = search_key(f"{place.area_tr} {place.area_en}").split()
            return bool(words) and all(_word_hits(w, area) for w in words)

        chosen = [p for p in places if not is_generic_area(p.area_tr) and area_hits(p)]
    if not chosen:
        blocks = sorted({p.building for p in places if p.building})
        areas = sorted({p.area_tr for p in places if not is_generic_area(p.area_tr)})
        return {
            "error": f"no block or tour area matches {query!r}",
            "blocks": blocks,
            "areas": areas[:MAX_DESCRIBE_ROOMS],
        }
    name = (lambda p: p.name_tr) if lang == "tr" else (lambda p: p.name_en)
    floors = sorted({p.floor for p in chosen if p.floor is not None})
    rooms = [p for p in chosen if p.kind is NodeKind.INDOOR]
    by_floor: list[dict[str, Any]] = []
    budget = MAX_DESCRIBE_ROOMS
    for floor in [*floors, None]:
        here = sorted({name(p) for p in rooms if p.floor == floor})[:budget]
        budget -= len(here)
        if here:
            label = (
                None
                if floor is None
                else (floor_tr(floor) if lang == "tr" else floor_en(floor))
            )
            by_floor.append({"floor": label, "rooms": here})
    return {
        "block": code,
        "areas": sorted(
            {
                p.area_tr if lang == "tr" else p.area_en
                for p in chosen
                if not is_generic_area(p.area_tr)
            }
        ),
        # Only floors with a 360° spot: the tour, not the building plan.
        "floors_in_tour": [
            floor_tr(f) if lang == "tr" else floor_en(f) for f in floors
        ],
        "floor_count_in_tour": len(floors),
        "rooms_by_floor": by_floor,  # "floor": null = floor not in the label
        "rooms_listed": MAX_DESCRIBE_ROOMS - budget,
        "rooms_total": len({(p.name_tr, p.floor) for p in rooms}),
        "entrances": sorted({name(p) for p in chosen if p.kind is NodeKind.ENTRANCE}),
    }


def build_agent(model: Model) -> Agent[AssistantDeps, str]:
    agent: Agent[AssistantDeps, str] = Agent(
        model,
        deps_type=AssistantDeps,
        instructions=PROMPT,
        model_settings=MODEL_SETTINGS,
        capabilities=[ProcessHistory(processor=keep_recent)],
        name="campus-assistant",
    )

    @agent.instructions
    def language(ctx: RunContext[AssistantDeps]) -> str:
        # Sources are mostly Turkish; without this the model drifts into them.
        if ctx.deps.lang == "en":
            return (
                "The visitor's interface is in English: answer in English, "
                "translating Turkish source text, unless they write in Turkish."
            )
        return (
            "Ziyaretçinin arayüzü Türkçe: kullanıcı başka bir dilde yazmadıkça "
            "Türkçe yanıt ver."
        )

    @agent.tool(name="search_places")
    def search_places_tool(
        ctx: RunContext[AssistantDeps], query: str
    ) -> list[dict[str, Any]]:
        """Find campus places by name: building entrances, open areas, rooms,
        and businesses and services (yemekhane/canteen, cafés, shops, health
        centre, student affairs) with their block, floor and category.

        When no name has every word, close matches are returned: use one only
        if it is clearly the place asked about. An empty list means the map
        cannot route there yet.
        """
        return [_place_summary(p) for p in find_places(ctx.deps.places, query)]

    @agent.tool
    def get_route(
        ctx: RunContext[AssistantDeps],
        to_place: str,
        from_place: str = DEFAULT_START,
        avoid_stairs: bool = False,
    ) -> dict[str, Any]:
        """Shortest walking route between two places; the map draws it.

        Places are entrances, open areas and rooms: a route to a room enters
        its block and takes the stairs to its floor. Indoor lengths are
        estimates (``approximate``). An unresolved or ambiguous name returns
        an error with ``did_you_mean``: call again with one of those ids.

        Args:
            to_place: destination name or place id.
            from_place: start name or place id (default: the main campus entrance).
            avoid_stairs: prefer a step-free route.
        """
        start = _resolve(ctx.deps, from_place)
        end = _resolve(ctx.deps, to_place)
        if start is None or end is None:
            # A short list of close names lets the model pick the right place
            # (or ask) in one step instead of guessing over several rounds.
            return _unresolved(ctx.deps, from_place if start is None else to_place)
        try:
            route = shortest_route(ctx.deps.store, start.id, end.id, avoid_stairs)
        except NoRouteError:
            return {"error": "no walkable route between these places yet"}
        texts = [instruction(s, end.name_tr, end.name_en) for s in route.steps]
        return {
            "from": _place_summary(start),
            "to": _place_summary(end),
            "node_ids": route.node_ids,
            "length_m": round(route.length_m),
            "duration_min": max(1, round(route.duration_s / 60)),
            "approximate": route.approximate,  # indoor lengths are estimates
            "steps_tr": [tr for tr, _ in texts],
            "steps_en": [en for _, en in texts],
        }

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[AssistantDeps], query: str, lang: Literal["tr", "en"]
    ) -> list[dict[str, Any]]:
        """Search descriptions of 360° spots, buildings, floors and rooms.

        Also covers accessibility (steps, ramps, lifts) and what is at an
        entrance.

        Args:
            query: what to look for, in the user's words.
            lang: language of the user's question.
        """
        if ctx.deps.knowledge is None:
            return [{"error": "knowledge base unavailable"}]
        try:
            hits = await ctx.deps.knowledge.search(query, lang)
        except Exception as exc:  # embedding quota (429), network, database
            # Degrade instead of failing the whole chat: routes still work.
            status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            log.warning("knowledge search failed: %s %s", type(exc).__name__, status)
            return [{"error": KNOWLEDGE_DOWN}]
        return [
            {
                "title": h["title"],
                "content": h["content"][:MAX_CHUNK_CHARS],
                "building": (h["metadata"] or {}).get("building"),
                "floor": (h["metadata"] or {}).get("floor"),
                "node_id": (h["metadata"] or {}).get("node_id"),
                "score": round(float(h["score"]), 3),
            }
            for h in hits
        ]

    @agent.tool
    def describe_place(
        ctx: RunContext[AssistantDeps], name: str, lang: Literal["tr", "en"]
    ) -> dict[str, Any]:
        """Floors, rooms per floor and entrances of a block or tour area.

        Use it for "how many floors does X have", "which floors", "what is
        in T Blok / the library". Built from the walking map's tour labels,
        so it counts the floors the 360° tour covers.

        Args:
            name: a block ("T Blok", "M Block") or an area ("Kütüphane").
            lang: language of the user's question.
        """
        return describe(ctx.deps.places, name, lang)

    return agent
