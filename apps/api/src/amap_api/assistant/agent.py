"""The campus assistant agent (pydantic-ai) and its tools.

Models: Groq ``openai/gpt-oss-120b`` first, then the smaller ``gpt-oss-20b``
and Gemini Flash-Lite when a model is rate-limited or down (free tiers). The
history is trimmed to the last few turns before each request: Groq's free
tier allows 8K tokens per minute.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic_ai import Agent, ModelSettings, RunContext, UsageLimits
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import Model

from amap_api.assistant.knowledge import Knowledge
from amap_api.directions import instruction
from amap_api.graph_store import GraphStore
from amap_api.routing import NoRouteError, shortest_route
from amap_contracts.graph import NodeKind
from amap_contracts.places import Place, search_places

PROMPT = (Path(__file__).parent / "prompts" / "assistant_v2.md").read_text("utf-8")
DEFAULT_START = "Kampüs Girişi"
KEEP_MESSAGES = 8

MODEL_SETTINGS = ModelSettings(max_tokens=700, temperature=0.3)
USAGE_LIMITS = UsageLimits(request_limit=5, total_tokens_limit=24_000)


@dataclass(slots=True)
class AssistantDeps:
    store: GraphStore
    places: list[Place]
    knowledge: Knowledge | None
    lang: Literal["tr", "en"] = "tr"  # the visitor's interface language


def keep_recent(messages: list[ModelMessage]) -> list[ModelMessage]:
    """The last few messages, starting at a user turn so tool calls stay paired."""
    if len(messages) <= KEEP_MESSAGES:
        return messages
    tail = messages[-KEEP_MESSAGES:]
    for i, message in enumerate(tail):
        if isinstance(message, ModelRequest) and any(
            isinstance(part, UserPromptPart) for part in message.parts
        ):
            return tail[i:]
    return messages[-1:]


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
    return {
        "id": place.id,
        "name_tr": place.name_tr,
        "name_en": place.name_en,
        "kind": place.kind.value,
        "building": place.building,
    }


def _resolve(deps: AssistantDeps, name: str) -> Place | None:
    by_id = {p.id: p for p in deps.places}
    if name in by_id:
        return by_id[name]
    found = search_places(deps.places, name, limit=1)
    if found:
        return found[0]
    if name == DEFAULT_START:
        # Graphs without the main gate (tests, partial runs): any open area.
        return next((p for p in deps.places if p.kind is NodeKind.OUTDOOR), None)
    return None


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
        """Find routable campus places (entrances, open areas) by name."""
        return [_place_summary(p) for p in search_places(ctx.deps.places, query, 5)]

    @agent.tool
    def get_route(
        ctx: RunContext[AssistantDeps],
        to_place: str,
        from_place: str = DEFAULT_START,
        avoid_stairs: bool = False,
    ) -> dict[str, Any]:
        """Shortest walking route between two places; the map draws it.

        Args:
            to_place: destination name or place id.
            from_place: start name or place id (default: the main campus entrance).
            avoid_stairs: prefer a step-free route.
        """
        start = _resolve(ctx.deps, from_place)
        end = _resolve(ctx.deps, to_place)
        if start is None or end is None:
            missing = from_place if start is None else to_place
            return {"error": f"no routable place matches {missing!r}"}
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
            "steps_tr": [tr for tr, _ in texts],
            "steps_en": [en for _, en in texts],
        }

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[AssistantDeps], query: str, lang: Literal["tr", "en"]
    ) -> list[dict[str, Any]]:
        """Search descriptions of 360° spots, buildings, floors and rooms.

        Args:
            query: what to look for, in the user's words.
            lang: language of the user's question.
        """
        if ctx.deps.knowledge is None:
            return [{"error": "knowledge base unavailable"}]
        hits = await ctx.deps.knowledge.search(query, lang)
        return [
            {
                "title": h["title"],
                "content": h["content"][:600],
                "building": (h["metadata"] or {}).get("building"),
                "floor": (h["metadata"] or {}).get("floor"),
                "node_id": (h["metadata"] or {}).get("node_id"),
                "score": round(float(h["score"]), 3),
            }
            for h in hits
        ]

    return agent
