"""Graph helpers over the tour's navigation links."""

from collections import deque
from collections.abc import Collection, Iterable, Mapping

from amap_pipeline.tour.parse import Scene

Adjacency = dict[str, set[str]]


def build_adjacency(scenes: Iterable[Scene]) -> Adjacency:
    """Undirected adjacency restricted to the given scenes (dangling links dropped)."""
    scene_list = list(scenes)
    names = {s.name for s in scene_list}
    adj: Adjacency = {name: set() for name in names}
    for scene in scene_list:
        for target in scene.nav_links:
            if target in names and target != scene.name:
                adj[scene.name].add(target)
                adj[target].add(scene.name)
    return adj


def connected_components(adj: Mapping[str, set[str]]) -> list[set[str]]:
    """Components sorted by size (largest first), ties broken by smallest name."""
    seen: set[str] = set()
    components: list[set[str]] = []
    for start in sorted(adj):
        if start in seen:
            continue
        component: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            component.add(node)
            stack.extend(adj[node] - seen)
        components.append(component)
    components.sort(key=lambda c: (-len(c), min(c)))
    return components


def bfs_select(
    adj: Mapping[str, set[str]],
    hub: str,
    n: int,
    allowed: Collection[str] | None = None,
) -> list[str]:
    """Return up to ``n`` scenes reachable from ``hub`` in deterministic BFS order.

    Only scenes in ``allowed`` are visited (the hub must be allowed too).
    """
    if hub not in adj:
        raise KeyError(f"Hub scene {hub!r} is not in the graph")
    if allowed is not None and hub not in allowed:
        raise ValueError(f"Hub scene {hub!r} is not an allowed scene")
    if n <= 0:
        return []
    order: list[str] = []
    visited = {hub}
    queue = deque([hub])
    while queue and len(order) < n:
        node = queue.popleft()
        order.append(node)
        for neighbour in sorted(adj[node]):
            if neighbour in visited:
                continue
            if allowed is not None and neighbour not in allowed:
                continue
            visited.add(neighbour)
            queue.append(neighbour)
    return order
