"""FastAPI application factory.

Run with ``uvicorn amap_api.main:create_app --factory`` so that importing the
module (tests, OpenAPI export) never reads the local ``.env``.
"""

import logging
import math
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from amap_api import __version__
from amap_api.assistant.agent import (
    USAGE_LIMITS,
    AssistantDeps,
    build_agent,
    build_model,
)
from amap_api.assistant.knowledge import Knowledge
from amap_api.assistant.testing import offline_model
from amap_api.db import Database
from amap_api.directions import instruction
from amap_api.graph_store import GraphStore, load_graph
from amap_api.http_cache import CachedJson
from amap_api.places import Place, build_places, search_places
from amap_api.rate_limit import TokenBucket
from amap_api.routing import NoRouteError, drawable_parts, shortest_route
from amap_api.schemas import (
    BuildingOut,
    ErrorOut,
    Health,
    NearestNode,
    PlaceOut,
    RouteRequest,
    RouteResponse,
    StepOut,
    WeatherOut,
)
from amap_api.settings import Settings, get_settings
from amap_api.weather import WeatherService, WeatherUnavailableError
from amap_contracts import search_key
from amap_contracts.graph import NodeKind

log = logging.getLogger("amap_api")
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

MAX_CHAT_CHARS = 1000
# The graph and the place directory change only when the API restarts.
CACHE_MAX_AGE_S = 300
# About three questions a minute per visitor, with a short burst.
CHAT_BUCKET = TokenBucket(capacity=6, refill_per_s=1 / 20)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )


def _last_user_chars(body: dict[str, Any]) -> int:
    """Characters in the newest user message of an AI SDK UI-message request."""
    for message in reversed(body.get("messages") or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return sum(
                len(str(part.get("text", "")))
                for part in message.get("parts") or []
                if isinstance(part, dict) and part.get("type") == "text"
            )
    return 0


def require_store(request: Request) -> GraphStore:
    loaded: GraphStore | None = request.app.state.store
    if loaded is None:
        raise HTTPException(503, "walking graph is not loaded")
    return loaded


StoreDep = Annotated[GraphStore, Depends(require_store)]


def require_database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise HTTPException(503, "database is not configured")
    return database


DatabaseDep = Annotated[Database, Depends(require_database)]


def create_app(
    settings: Settings | None = None,
    store: GraphStore | None = None,
    database: Database | None = None,
) -> FastAPI:
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loaded = store
        if loaded is None:
            try:
                loaded = load_graph(cfg.graph_source)
            except (OSError, httpx.HTTPError, ValueError) as exc:
                log.warning(
                    "walking graph not loaded from %s: %s", cfg.graph_source, exc
                )
        app.state.store = loaded
        app.state.places = build_places(loaded) if loaded else []
        # 1.1 MB of GeoJSON: serialised once, compressed per request.
        app.state.graph_json = (
            CachedJson.of(loaded.graph.to_geojson()) if loaded else None
        )
        app.state.directory = [
            place_out(p)
            for p in app.state.places
            if loaded
            and p.kind is not NodeKind.INDOOR
            and not loaded.nodes[p.id].approximate
        ]
        app.state.http = httpx.AsyncClient()
        app.state.weather = WeatherService(app.state.http, ttl_s=cfg.weather_ttl_s)
        db = database
        if db is None and cfg.amap_api_database_url:
            db = Database(cfg.amap_api_database_url)
            await db.open()
        app.state.database = db
        app.state.assistant = None
        try:
            model = (
                offline_model()
                if cfg.amap_assistant_model == "offline"
                else build_model(cfg.groq_api_key, cfg.gemini_api_key)
            )
            app.state.assistant = build_agent(model)
        except ValueError as exc:
            log.warning("assistant disabled: %s", exc)
        app.state.knowledge = (
            Knowledge(db, cfg.gemini_api_key) if db and cfg.gemini_api_key else None
        )
        yield
        await app.state.http.aclose()
        if db is not None and database is None:
            await db.close()

    app = FastAPI(title="Aydın Campus Map API", version=__version__, lifespan=lifespan)
    if cfg.asset_dir and Path(cfg.asset_dir).is_dir():
        app.mount("/assets", StaticFiles(directory=cfg.asset_dir), name="assets")
    # Text/event-stream (the chat) is never compressed: it would stop streaming.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Amap-Locale"],
        expose_headers=["x-vercel-ai-ui-message-stream"],
    )

    def place_out(place: Place) -> PlaceOut:
        return PlaceOut(
            id=place.id,
            name_tr=place.name_tr,
            name_en=place.name_en,
            kind=place.kind,
            building=place.building,
            node_ids=list(place.node_ids),
            floor=place.floor,
            area_tr=place.area_tr,
            area_en=place.area_en,
        )

    @app.get("/health", response_model=Health)
    async def health(request: Request) -> Health:
        """Liveness; with a database it also runs `select 1` (keeps Supabase awake)."""
        loaded: GraphStore | None = request.app.state.store
        db: Database | None = request.app.state.database
        if db is None:
            database_state = "off"
        else:
            database_state = "ok" if await db.ping() else "unavailable"
        return Health(
            status="ok",
            graph_loaded=loaded is not None,
            nodes=len(loaded.graph.nodes) if loaded else 0,
            edges=len(loaded.graph.edges) if loaded else 0,
            database=database_state,
            version=__version__,
        )

    @app.get(
        "/graph",
        response_model=dict[str, Any],
        responses={304: {"description": "Not modified (If-None-Match)"}},
    )
    def graph(request: Request, store: StoreDep) -> Response:
        """The walking graph as GeoJSON (nodes and edges); ETag-cached."""
        cached: CachedJson | None = request.app.state.graph_json
        if cached is None:  # a store given directly (tests)
            cached = CachedJson.of(store.graph.to_geojson())
            request.app.state.graph_json = cached
        return cached.response(request, CACHE_MAX_AGE_S)

    @app.get(
        "/places",
        response_model=list[PlaceOut],
        responses={304: {"description": "Not modified (If-None-Match)"}},
    )
    async def places(
        request: Request,
        q: Annotated[str | None, Query(max_length=100)] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> list[PlaceOut] | Response:
        """Word-prefix search; with a database, typos fall back to trigrams.

        Without ``q``: the places the map shows (open areas and entrances at
        measured spots); rooms and doors known only from the tour are found
        by searching.
        """
        all_places: list[Place] = request.app.state.places
        if not q:
            directory: list[PlaceOut] = request.app.state.directory
            listed = [p.model_dump(mode="json") for p in directory[:limit]]
            return CachedJson.of(listed).response(request, CACHE_MAX_AGE_S)
        found = search_places(all_places, q, limit)
        db: Database | None = request.app.state.database
        key = search_key(q)
        if not found and db is not None and len(key) >= 3:
            by_id = {p.id: p for p in all_places}
            try:
                ids = await db.similar_place_ids(key, limit)
            except Exception as exc:
                log.warning("trigram search failed: %s", type(exc).__name__)
                ids = []
            found = [by_id[i] for i in ids if i in by_id]
        return [place_out(p) for p in found]

    @app.get(
        "/buildings",
        response_model=list[BuildingOut],
        responses={503: {"model": ErrorOut}},
    )
    async def buildings(
        database: DatabaseDep, campus: Annotated[bool, Query()] = True
    ) -> list[BuildingOut]:
        """Building massing summary (campus blocks by default)."""
        return [BuildingOut(**row) for row in await database.buildings(campus)]

    @app.get("/nodes/nearest", response_model=NearestNode)
    def nearest(
        store: StoreDep,
        lat: Annotated[float, Query(ge=-90, le=90)],
        lng: Annotated[float, Query(ge=-180, le=180)],
    ) -> NearestNode:
        """Nearest outdoor/entrance panorama to a map click (equirectangular metres).

        Indoor spots stand at borrowed positions and are never the answer.
        """
        k = 111_320.0
        candidates = [
            n
            for n in store.graph.nodes
            if n.kind in (NodeKind.OUTDOOR, NodeKind.ENTRANCE) and not n.approximate
        ] or store.graph.nodes
        best = min(
            candidates,
            key=lambda n: math.hypot(
                (n.lng - lng) * k * math.cos(math.radians(lat)), (n.lat - lat) * k
            ),
        )
        distance = math.hypot(
            (best.lng - lng) * k * math.cos(math.radians(lat)), (best.lat - lat) * k
        )
        return NearestNode(node_id=best.id, distance_m=round(distance, 1))

    @app.post(
        "/route",
        response_model=RouteResponse,
        responses={404: {"model": ErrorOut}, 422: {"model": ErrorOut}},
    )
    def route(body: RouteRequest, store: StoreDep) -> RouteResponse:
        try:
            found = shortest_route(store, body.source, body.target, body.avoid_stairs)
        except KeyError as exc:
            raise HTTPException(404, f"unknown node {exc.args[0]}") from exc
        except NoRouteError as exc:
            raise HTTPException(422, str(exc)) from exc
        dest = store.nodes[body.target]
        steps = []
        for step in found.steps:
            tr, en = instruction(step, dest.label.tr, dest.label.en)
            steps.append(StepOut(**asdict(step), text_tr=tr, text_en=en))
        return RouteResponse(
            node_ids=found.node_ids,
            length_m=round(found.length_m, 1),
            duration_s=round(found.duration_s, 1),
            coordinates=[
                (store.nodes[n].lng, store.nodes[n].lat) for n in found.node_ids
            ],
            parts=[
                [(store.nodes[n].lng, store.nodes[n].lat) for n in part]
                for part in drawable_parts(store, found.node_ids)
            ],
            steps=steps,
            approximate=found.approximate,
        )

    @app.get(
        "/weather", response_model=WeatherOut, responses={503: {"model": ErrorOut}}
    )
    async def weather(request: Request) -> WeatherOut:
        service: WeatherService = request.app.state.weather
        try:
            current = await service.current()
        except WeatherUnavailableError as exc:
            raise HTTPException(503, str(exc)) from exc
        return WeatherOut(**asdict(current))

    @app.post(
        "/chat",
        responses={
            413: {"model": ErrorOut},
            429: {"model": ErrorOut},
            503: {"model": ErrorOut},
        },
    )
    async def chat(request: Request, store: StoreDep) -> Response:
        """Campus assistant; streams the Vercel AI SDK UI message protocol (v7)."""
        from pydantic_ai.ui.vercel_ai import VercelAIAdapter

        agent = request.app.state.assistant
        if agent is None:
            raise HTTPException(503, "assistant is not configured")
        if not CHAT_BUCKET.allow(_client_key(request)):
            raise HTTPException(429, "too many questions, wait a moment")
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(422, "invalid JSON body") from exc
        if _last_user_chars(body if isinstance(body, dict) else {}) > MAX_CHAT_CHARS:
            raise HTTPException(
                413, f"questions are limited to {MAX_CHAT_CHARS} characters"
            )
        deps = AssistantDeps(
            store=store,
            places=request.app.state.places,
            knowledge=request.app.state.knowledge,
            lang="en" if request.headers.get("x-amap-locale") == "en" else "tr",
        )
        return await VercelAIAdapter.dispatch_request(
            request,
            agent=agent,
            sdk_version=7,
            deps=deps,
            usage_limits=USAGE_LIMITS,
        )

    return app
