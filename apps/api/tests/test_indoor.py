"""Routes into buildings: indoor steps, estimates, rooms as places (synthetic)."""

from itertools import pairwise

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from amap_api.assistant.agent import AssistantDeps, build_agent
from amap_api.directions import instruction
from amap_api.graph_store import GraphStore
from amap_api.places import build_places
from amap_api.routing import (
    PASSAGE_S,
    NoRouteError,
    Step,
    Turn,
    drawable_parts,
    shortest_route,
)
from amap_contracts.graph import (
    WALKING_SPEED_MPS,
    Edge,
    EdgeKind,
    EdgeOrigin,
    LengthSource,
    LocalizedText,
    NodeKind,
)


def test_shortest_route_into_basement_lab_has_indoor_steps(
    indoor_store: GraphStore,
) -> None:
    route = shortest_route(indoor_store, "gate", "lab")
    assert route.node_ids == ["gate", "yard", "m", "m1", "lab"], route.node_ids
    turns = [s.turn for s in route.steps]
    expected = [Turn.START, Turn.RIGHT, Turn.ENTER, Turn.STAIRS_DOWN, Turn.ARRIVE]
    assert turns == expected, f"Got {turns}"
    enter, stairs, arrive = route.steps[2:]
    assert (enter.node_id, enter.building, enter.indoor) == ("m", "M", True), enter
    assert (stairs.floors, stairs.floor, stairs.bearing_deg) == (-1, -1, 0.0), stairs
    assert (arrive.building, arrive.floor) == ("M", -1), arrive


def test_shortest_route_indoor_flags_estimates_and_counts_stairs(
    indoor_store: GraphStore,
) -> None:
    route = shortest_route(indoor_store, "gate", "lab")
    assert route.approximate is True, "indoor lengths are estimates"
    assert route.length_m == pytest.approx(104.0), f"Got {route.length_m}"
    expected = 104.0 / WALKING_SPEED_MPS + 15.0  # one flight of stairs
    assert route.duration_s == pytest.approx(expected), f"Got {route.duration_s}"
    distances = [round(s.distance_m) for s in route.steps]
    assert distances == [40, 40, 12, 12, 0], f"Got {distances}"


def test_shortest_route_room_to_room_exits_and_enters(
    indoor_store: GraphStore,
) -> None:
    route = shortest_route(indoor_store, "lab", "class_d")
    turns = [s.turn for s in route.steps]
    expected = [
        Turn.START,  # in the lab
        Turn.GO_TO,  # the -1 corridor
        Turn.STAIRS_UP,  # to M Blok's door
        Turn.EXIT,  # out of M Blok, walking on
        Turn.RIGHT,
        Turn.ENTER,  # D Blok
        Turn.GO_TO,
        Turn.STAIRS_UP,
        Turn.ARRIVE,
    ]
    assert turns == expected, f"Got {turns}"
    exit_step = route.steps[3]
    assert (exit_step.building, exit_step.indoor) == ("M", False), exit_step
    assert route.steps[7].floors == 3, route.steps[7]


def test_shortest_route_stairs_down_then_up_merges_one_flight(
    indoor_store: GraphStore,
) -> None:
    route = shortest_route(indoor_store, "lab", "class_m")
    stairs = [s for s in route.steps if s.turn is Turn.STAIRS_UP]
    assert [s.floors for s in stairs] == [6], "-1 -> door (0) -> 5 is one climb"
    assert route.steps[-1].turn is Turn.ARRIVE, route.steps


def test_shortest_route_outdoor_trip_avoids_foreign_buildings(
    indoor_store: GraphStore,
) -> None:
    # Through the passage p is shorter (72 m vs 90 m) but only an estimate.
    route = shortest_route(indoor_store, "m", "x")
    assert route.node_ids == ["m", "x"], route.node_ids
    assert route.approximate is False, "measured all the way"
    assert PASSAGE_S > 0, "the surcharge is what keeps it outside"


def test_shortest_route_into_passage_uses_it(indoor_store: GraphStore) -> None:
    route = shortest_route(indoor_store, "gate", "p")
    assert route.node_ids[-2:] == ["m", "p"], route.node_ids
    # The passage names no block: the door it is entered by does.
    tr, en = instruction(route.steps[-2], "Geçit", "Passage")
    assert (tr, en) == ("M Blok'a girin", "Enter M Block"), (tr, en)


def test_shortest_route_avoid_stairs_has_no_way_down(
    indoor_store: GraphStore,
) -> None:
    with pytest.raises(NoRouteError):
        shortest_route(indoor_store, "gate", "lab", avoid_stairs=True)


def test_graph_store_indoor_clusters_split_at_measured_doors(
    indoor_store: GraphStore,
) -> None:
    cluster = indoor_store.indoor_cluster
    assert cluster["m1"] == cluster["lab"] == cluster["lab2"], cluster
    assert cluster["m1"] == cluster["class_m"], "joined by the menu jump"
    assert cluster["m1"] != cluster["d0"], "another building's spots"
    assert "m" not in cluster and "gate" not in cluster, "measured nodes"


def test_instruction_leaves_out_a_floor_the_label_contradicts() -> None:
    # Whatever the floor resolution says, "T Blok -2.Kat" never reads "2. kat".
    step = Step("t", Turn.ARRIVE, 0.0, 0.0, indoor=True, building="T", floor=2)
    tr, en = instruction(step, "T Blok -2.Kat", "T Block -2.Floor")
    assert (tr, en) == (
        "Vardınız: T Blok -2.Kat (T Blok)",
        "You have arrived: T Block -2.Floor (T Block)",
    ), (tr, en)


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (
            Step("m", Turn.ENTER, 12.0, 0.0, indoor=True, building="M"),
            ("M Blok'a girin", "Enter M Block"),
        ),
        (
            Step("g", Turn.ENTER, 12.0, 0.0, indoor=True),
            ("Binaya girin", "Enter the building"),
        ),
        (
            Step(
                "k",
                Turn.ENTER,
                12.0,
                0.0,
                indoor=True,
                place=LocalizedText(tr="Kütüphane", en="Library"),
            ),
            ("Kütüphane binasına girin", "Enter Library"),
        ),
        (
            Step("m5", Turn.STAIRS_UP, 12.0, 0.0, indoor=True, floor=5, floors=5),
            (
                "Merdivenle 5 kat çıkın (5. kat)",
                "Take the stairs up 5 floors to floor 5",
            ),
        ),
        (
            Step("m", Turn.STAIRS_DOWN, 0.0, 0.0, indoor=True, floor=0, floors=-1),
            (
                "Merdivenle 1 kat inin (zemin kat)",
                "Take the stairs down 1 floor to the ground floor",
            ),
        ),
        (
            Step("m", Turn.EXIT, 31.0, 180.0, building="M"),
            (
                "M Blok'tan çıkın, güney yönünde 30 m yürüyün",
                "Leave M Block and head south for 30 m",
            ),
        ),
        (
            Step(
                "c",
                Turn.GO_TO,
                12.0,
                0.0,
                indoor=True,
                place=LocalizedText(tr="Koridor", en="Corridor"),
            ),
            ("Devam edin: Koridor", "Continue to Corridor"),
        ),
        (
            Step(
                "lab",
                Turn.START,
                12.0,
                0.0,
                indoor=True,
                building="M",
                floor=5,
                place=LocalizedText(tr="Anatomi Lab", en="Anatomy Lab"),
            ),
            (
                "Yola çıkın: Anatomi Lab (M Blok, 5. kat)",
                "Start at Anatomy Lab (M Block, floor 5)",
            ),
        ),
        (
            Step("lab", Turn.ARRIVE, 0.0, 0.0, indoor=True, building="M", floor=-1),
            (
                "Vardınız: Anatomi Lab (M Blok, \u22121. kat)",
                "You have arrived: Anatomy Lab (M Block, floor \u22121)",
            ),
        ),
    ],
)
def test_instruction_indoor_steps_are_bilingual(
    step: Step, expected: tuple[str, str]
) -> None:
    got = instruction(step, "Anatomi Lab", "Anatomy Lab")
    assert got == expected, f"Got {got}"


def test_route_endpoint_marks_estimates_and_indoor_steps(
    indoor_client: TestClient,
) -> None:
    response = indoor_client.post("/route", json={"source": "gate", "target": "lab"})
    body = response.json()
    assert response.status_code == 200, body
    assert body["approximate"] is True, body
    stairs = body["steps"][3]
    assert stairs["turn"] == "stairs_down" and stairs["indoor"] is True, stairs
    assert (stairs["floor"], stairs["floors"]) == (-1, -1), stairs
    assert stairs["place"] == {"tr": "M Blok -1.Kat", "en": "M Block -1.Floor"}
    assert stairs["text_tr"] == "Merdivenle 1 kat inin (\u22121. kat)", stairs
    last = body["steps"][-1]["text_tr"]
    assert last == "Vardınız: Anatomi Lab (M Blok, \u22121. kat)", last


def test_route_endpoint_avoid_stairs_indoors_returns_422(
    indoor_client: TestClient,
) -> None:
    response = indoor_client.post(
        "/route", json={"source": "gate", "target": "lab", "avoid_stairs": True}
    )
    assert response.status_code == 422, response.text


def test_places_search_finds_rooms_with_block_and_floor(
    indoor_client: TestClient,
) -> None:
    body = indoor_client.get("/places", params={"q": "anatomi lab"}).json()
    assert [p["name_tr"] for p in body] == ["Anatomi Lab"], body
    room = body[0]
    assert (room["kind"], room["building"], room["floor"]) == ("indoor", "M", -1)
    assert room["node_ids"] == ["lab", "lab2"], "one room, two panoramas"
    assert room["area_tr"] == "Sağlık Bilimleri", room


def test_places_search_same_name_rooms_stay_apart(indoor_client: TestClient) -> None:
    body = indoor_client.get("/places", params={"q": "derslik"}).json()
    found = [(p["building"], p["floor"]) for p in body]
    assert found == [("D", 3), ("M", 5)], f"Got {found}"


def test_places_search_block_lists_its_entrance_first(
    indoor_client: TestClient,
) -> None:
    body = indoor_client.get("/places", params={"q": "m blok"}).json()
    assert body[0]["name_tr"] == "M Blok Giriş", [p["name_tr"] for p in body]
    kinds = [p["kind"] for p in body]
    first_room = kinds.index("indoor")
    assert set(kinds[first_room:]) == {"indoor"}, f"doors before rooms: {kinds}"


def test_places_directory_leaves_rooms_to_search(indoor_client: TestClient) -> None:
    body = indoor_client.get("/places").json()
    names = [p["name_tr"] for p in body]
    expected = ["D Blok Giriş", "Kampüs", "Kampüs Girişi", "M Blok Giriş"]
    assert names == expected, "measured spots only: no rooms, no borrowed doors"


def test_places_search_finds_doors_known_from_the_tour(
    indoor_client: TestClient,
) -> None:
    body = indoor_client.get("/places", params={"q": "yan giris"}).json()
    assert [p["id"] for p in body] == ["side"], body


def test_nearest_node_skips_indoor_spots(indoor_client: TestClient) -> None:
    door = indoor_client.get(
        "/nodes/nearest",
        params={"lat": 40.9915 + 40 / 111_320.0, "lng": 28.7971 + 40 / 84_000.0},
    ).json()
    assert door["node_id"] == "m", door


def test_assistant_get_route_reaches_a_room(indoor_store: GraphStore) -> None:
    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        answered = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        )
        if answered:
            return ModelResponse(parts=[TextPart("Haritada.")])
        args = {"to_place": "Anatomi Lab", "from_place": "Kampüs Girişi"}
        return ModelResponse(parts=[ToolCallPart("get_route", args)])

    deps = AssistantDeps(
        store=indoor_store, places=build_places(indoor_store), knowledge=None
    )
    result = build_agent(FunctionModel(respond)).run_sync(
        "Anatomi laboratuvarına nasıl giderim?", deps=deps
    )
    returned = next(
        part.content
        for message in result.all_messages()
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "get_route"
    )
    assert isinstance(returned, dict), returned
    assert returned["node_ids"][-1] == "lab", returned
    assert "Merdivenle 1 kat inin (\u22121. kat)" in returned["steps_tr"], returned
    assert returned["to"]["building"] == "M", returned


def test_shortest_route_destination_panoramas_need_no_go_to(
    indoor_store: GraphStore,
) -> None:
    # lab and lab2 are one room: walking through lab to lab2 is arriving.
    route = shortest_route(indoor_store, "gate", "lab2")
    turns = [s.turn for s in route.steps]
    assert Turn.GO_TO not in turns, f"Got {turns}"
    assert route.steps[-1].node_id == "lab2", route.steps[-1]


def _door_store(store: GraphStore, passage: bool) -> GraphStore:
    """M Blok's side door (known only from the tour, at m) leads to D Blok's
    entrance x: through a building (a passage) or by a walk outside. The
    walk m-x and the passage p-x are gone; a lawn lies 40 m east of x."""
    graph = store.graph
    x = store.nodes["x"]
    lawn = x.model_copy(
        update={
            "id": "lawn",
            "kind": NodeKind.OUTDOOR,
            "enu": (140.0, 40.0, 1.6),
            "lng": x.lng + 40 / 84_000.0,
            "label": LocalizedText(tr="Çimen", en="Lawn"),
            "building": None,
            "floor": None,
        }
    )

    def edge(
        a: str,
        b: str,
        length: float,
        kind: EdgeKind,
        passage: bool = False,
        source: LengthSource = LengthSource.ESTIMATE,
    ) -> Edge:
        return Edge(
            id=f"{a}|{b}",
            source=a,
            target=b,
            kind=kind,
            origin=EdgeOrigin.TOUR,
            length_m=length,
            cost_s=length / WALKING_SPEED_MPS,
            length_source=source,
            passage=passage,
        )

    edges = [e for e in graph.edges if e.id not in {"m|x", "p|x"}]
    edges += [
        edge("m", "side", 12.0, EdgeKind.ENTRANCE),
        edge("side", "x", 60.0, EdgeKind.ENTRANCE, passage=passage),
        edge("lawn", "x", 40.0, EdgeKind.OUTDOOR, source=LengthSource.SFM),
    ]
    nodes = [*graph.nodes, lawn]
    return GraphStore.from_graph(
        graph.model_copy(update={"nodes": nodes, "edges": edges})
    )


def test_shortest_route_passage_reads_as_walking_through(
    indoor_store: GraphStore,
) -> None:
    store = _door_store(indoor_store, passage=True)
    route = shortest_route(store, "gate", "lawn")
    assert route.node_ids == ["gate", "yard", "m", "side", "x", "lawn"], route
    turns = [s.turn for s in route.steps]
    expected = [Turn.START, Turn.RIGHT, Turn.THROUGH, Turn.EXIT, Turn.ARRIVE]
    assert turns == expected, f"Got {turns}"
    through, leave = route.steps[2:4]
    assert (through.building, through.indoor) == ("M", True), through
    assert round(through.distance_m) == 72, "door to far door, estimated"
    texts = [instruction(s, "Çimen", "Lawn")[0] for s in (through, leave)]
    assert texts == [
        "M Blok'un içinden geçin",
        "M Blok'tan çıkın, doğu yönünde 40 m yürüyün",
    ], texts


def test_drawable_parts_break_at_indoor_spots_and_passages(
    indoor_store: GraphStore,
) -> None:
    store = _door_store(indoor_store, passage=True)
    route = shortest_route(store, "gate", "lawn")
    parts = drawable_parts(store, route.node_ids)
    assert parts == [["gate", "yard", "m"], ["x", "lawn"]], parts


def test_shortest_route_door_outside_is_no_indoor_step(
    indoor_store: GraphStore,
) -> None:
    store = _door_store(indoor_store, passage=False)
    route = shortest_route(store, "gate", "lawn")
    turns = [s.turn for s in route.steps]
    # Past the side door outside, then on east: a turn, not a second start.
    assert turns == [Turn.START, Turn.RIGHT, Turn.GO_TO, Turn.STRAIGHT, Turn.ARRIVE]
    assert route.steps[2].indoor is False, "the side door is outside"
    assert drawable_parts(store, route.node_ids) == [
        ["gate", "yard", "m"],
        ["x", "lawn"],
    ]


def test_shortest_route_step_free_never_has_stairs(
    indoor_store: GraphStore,
) -> None:
    found = 0
    for source in indoor_store.nodes:
        for target in indoor_store.nodes:
            if source == target:
                continue
            try:
                route = shortest_route(indoor_store, source, target, avoid_stairs=True)
            except NoRouteError:
                continue
            found += 1
            stairs = [
                s.turn
                for s in route.steps
                if s.turn in (Turn.STAIRS_UP, Turn.STAIRS_DOWN)
            ]
            assert not stairs, f"{source} -> {target}: {stairs}"
    assert found >= 40, f"only {found} step-free routes"


def test_route_endpoint_parts_leave_out_borrowed_positions(
    indoor_client: TestClient,
) -> None:
    body = indoor_client.post("/route", json={"source": "gate", "target": "lab"}).json()
    assert len(body["coordinates"]) == 5, "one per node, for older clients"
    assert len(body["parts"]) == 1 and len(body["parts"][0]) == 3, body["parts"]


def test_graph_endpoint_is_compressed_and_revalidates(
    indoor_client: TestClient,
) -> None:
    first = indoor_client.get("/graph", headers={"Accept-Encoding": "gzip"})
    assert first.status_code == 200, first.text
    assert first.headers["content-encoding"] == "gzip", first.headers
    etag = first.headers["etag"]
    assert etag.startswith('W/"') and "max-age" in first.headers["cache-control"]
    again = indoor_client.get("/graph", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b"", again
    assert first.json()["type"] == "FeatureCollection"


def test_places_directory_revalidates(indoor_client: TestClient) -> None:
    first = indoor_client.get("/places", params={"limit": 50})
    again = indoor_client.get(
        "/places",
        params={"limit": 50},
        headers={"If-None-Match": first.headers["etag"]},
    )
    assert again.status_code == 304, again
    other = indoor_client.get(
        "/places", params={"limit": 2}, headers={"If-None-Match": first.headers["etag"]}
    )
    assert other.status_code == 200 and len(other.json()) == 2, other


def test_shortest_route_menu_jump_is_a_last_resort_even_indoors(
    indoor_store: GraphStore,
) -> None:
    # lab (-1) to class_m (5): the menu jump m1 -> class_m is one hop, but it
    # pays the passage penalty although both rooms are in M Blok's network.
    route = shortest_route(indoor_store, "lab", "class_m")
    assert "m" in route.node_ids, f"by the entrance hall: {route.node_ids}"
    edges = indoor_store.nx_graph.edges
    assert not any(edges[a, b].get("passage") for a, b in pairwise(route.node_ids)), (
        route.node_ids
    )


def test_shortest_route_step_free_never_takes_a_menu_jump(
    indoor_store: GraphStore,
) -> None:
    with pytest.raises(NoRouteError):
        shortest_route(indoor_store, "lab", "class_m", avoid_stairs=True)
