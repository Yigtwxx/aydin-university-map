import pytest

from amap_pipeline.tour import (
    Scene,
    bfs_select,
    build_adjacency,
    connected_components,
    florya_scenes,
)


@pytest.fixture
def adjacency(scenes: list[Scene]) -> dict[str, set[str]]:
    return build_adjacency(florya_scenes(scenes))


def test_build_adjacency_links_are_symmetric(adjacency: dict[str, set[str]]) -> None:
    for node, neighbours in adjacency.items():
        for other in neighbours:
            assert node in adjacency[other], f"{node} -> {other} is not symmetric"


def test_build_adjacency_drops_dangling_and_out_of_set_links(
    adjacency: dict[str, set[str]],
) -> None:
    assert adjacency["scene_900011"] == set(), "Dangling link must be dropped"
    assert "scene_900009" not in adjacency, "Other-campus scene must not appear"


def test_connected_components_largest_first(adjacency: dict[str, set[str]]) -> None:
    sizes = [len(c) for c in connected_components(adjacency)]
    assert sizes == [8, 1, 1], f"Unexpected component sizes {sizes}"


def test_bfs_select_outdoor_only_skips_indoor(adjacency: dict[str, set[str]]) -> None:
    allowed = {
        "scene_900001",
        "scene_900002",
        "scene_900003",
        "scene_900004",
        "scene_900005",
        "scene_900006",
    }
    result = bfs_select(adjacency, "scene_900001", 10, allowed)
    assert result == [
        "scene_900001",
        "scene_900002",
        "scene_900003",
        "scene_900004",
        "scene_900006",
        "scene_900005",
    ], f"Unexpected BFS order {result}"


def test_bfs_select_limit_truncates(adjacency: dict[str, set[str]]) -> None:
    result = bfs_select(adjacency, "scene_900001", 2)
    assert result == ["scene_900001", "scene_900002"], f"Got {result}"


def test_bfs_select_zero_returns_empty(adjacency: dict[str, set[str]]) -> None:
    assert bfs_select(adjacency, "scene_900001", 0) == []


def test_bfs_select_unknown_hub_raises_key_error(
    adjacency: dict[str, set[str]],
) -> None:
    with pytest.raises(KeyError):
        bfs_select(adjacency, "scene_000000", 3)


def test_bfs_select_hub_not_allowed_raises_value_error(
    adjacency: dict[str, set[str]],
) -> None:
    with pytest.raises(ValueError):
        bfs_select(adjacency, "scene_900007", 3, {"scene_900001"})
