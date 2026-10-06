import pytest

from amap_api.directions import compass_index, instruction
from amap_api.graph_store import GraphStore
from amap_api.routing import NoRouteError, Step, Turn, classify_turn, shortest_route


def test_shortest_route_prefers_short_stairs(store: GraphStore) -> None:
    route = shortest_route(store, "a", "d")
    assert route.node_ids == ["a", "d"], f"Got {route.node_ids}"
    assert route.length_m == pytest.approx(20.0), f"Got {route.length_m}"


def test_shortest_route_avoid_stairs_takes_detour(store: GraphStore) -> None:
    route = shortest_route(store, "a", "d", avoid_stairs=True)
    assert route.node_ids == ["a", "b", "c", "d"], f"Got {route.node_ids}"
    assert route.length_m == pytest.approx(60.0), f"Got {route.length_m}"


def test_shortest_route_isolated_target_raises_no_route(store: GraphStore) -> None:
    with pytest.raises(NoRouteError):
        shortest_route(store, "a", "e")


def test_shortest_route_unknown_node_raises_key_error(store: GraphStore) -> None:
    with pytest.raises(KeyError):
        shortest_route(store, "a", "zzz")


def test_route_steps_turn_right_at_corner(store: GraphStore) -> None:
    route = shortest_route(store, "a", "c")
    turns = [s.turn for s in route.steps]
    assert turns == [Turn.START, Turn.RIGHT, Turn.ARRIVE], f"Got {turns}"
    assert route.steps[0].bearing_deg == pytest.approx(0.0), "First leg heads north"


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (0, Turn.STRAIGHT), (15, Turn.STRAIGHT), (-45, Turn.SLIGHT_LEFT),
        (45, Turn.SLIGHT_RIGHT), (-90, Turn.LEFT), (90, Turn.RIGHT),
        (-135, Turn.SHARP_LEFT), (135, Turn.SHARP_RIGHT), (170, Turn.U_TURN),
    ],
)  # fmt: skip
def test_classify_turn_delta_maps_to_turn(delta: float, expected: Turn) -> None:
    assert classify_turn(delta) is expected, f"{delta}: {classify_turn(delta)}"


@pytest.mark.parametrize(("bearing", "index"), [(0, 0), (44, 1), (90, 2), (350, 0)])
def test_compass_index_rounds_to_eight_directions(bearing: float, index: int) -> None:
    assert compass_index(bearing) == index


def test_instruction_start_and_arrive_texts_are_bilingual() -> None:
    tr, en = instruction(Step("a", Turn.START, 23.0, 90.0), "Kütüphane", "Library")
    assert (tr, en) == ("Doğu yönünde 25 m yürüyün", "Head east for 25 m"), (tr, en)
    tr, en = instruction(Step("d", Turn.ARRIVE, 0.0, 0.0), "Kütüphane", "Library")
    assert tr == "Vardınız: Kütüphane" and en == "You have arrived: Library"
