"""FastAPI application factory.

Run with ``uvicorn amap_api.main:create_app --factory`` so that importing the
module (tests, OpenAPI export) never reads the local ``.env``.
"""

import logging
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from amap_api import __version__
from amap_api.directions import instruction
from amap_api.graph_store import GraphStore, load_graph
from amap_api.places import Place, build_places, search_places
from amap_api.routing import NoRouteError, shortest_route
from amap_api.schemas import (
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
from amap_contracts.graph import NodeKind

log = logging.getLogger("amap_api")


def require_store(request: Request) -> GraphStore:
    loaded: GraphStore | None = request.app.state.store
    if loaded is None:
        raise HTTPException(503, "walking graph is not loaded")
    return loaded


StoreDep = Annotated[GraphStore, Depends(require_store)]


def create_app(
    settings: Settings | None = None, store: GraphStore | None = None
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
        app.state.http = httpx.AsyncClient()
        app.state.weather = WeatherService(app.state.http, ttl_s=cfg.weather_ttl_s)
        yield
        await app.state.http.aclose()

    app = FastAPI(title="Aydın Campus Map API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def place_out(place: Place) -> PlaceOut:
        return PlaceOut(
            id=place.id,
            name_tr=place.name_tr,
            name_en=place.name_en,
            kind=place.kind,
            building=place.building,
            node_ids=list(place.node_ids),
        )

    @app.get("/health", response_model=Health)
    def health(request: Request) -> Health:
        loaded: GraphStore | None = request.app.state.store
        return Health(
            status="ok",
            graph_loaded=loaded is not None,
            nodes=len(loaded.graph.nodes) if loaded else 0,
            edges=len(loaded.graph.edges) if loaded else 0,
            version=__version__,
        )

    @app.get("/graph")
    def graph(store: StoreDep) -> dict[str, Any]:
        """The walking graph as GeoJSON (nodes and edges)."""
        return store.graph.to_geojson()

    @app.get("/places", response_model=list[PlaceOut])
    def places(
        request: Request,
        q: Annotated[str | None, Query(max_length=100)] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> list[PlaceOut]:
        all_places: list[Place] = request.app.state.places
        found = search_places(all_places, q, limit) if q else all_places[:limit]
        return [place_out(p) for p in found]

    @app.get("/nodes/nearest", response_model=NearestNode)
    def nearest(
        store: StoreDep,
        lat: Annotated[float, Query(ge=-90, le=90)],
        lng: Annotated[float, Query(ge=-180, le=180)],
    ) -> NearestNode:
        """Nearest outdoor/entrance panorama to a map click (equirectangular metres)."""
        k = 111_320.0
        candidates = [
            n
            for n in store.graph.nodes
            if n.kind in (NodeKind.OUTDOOR, NodeKind.ENTRANCE)
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
            steps=steps,
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

    return app
