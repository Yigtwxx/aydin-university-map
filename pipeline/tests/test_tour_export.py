from amap_pipeline.tour import Scene
from amap_pipeline.tour.export import classify_tour, scene_record


def test_scene_record_link_yaw_maps_hotspots_to_linked_scenes(
    scenes: list[Scene],
) -> None:
    tour = classify_tour(scenes)
    by_name = {s.name: s for s in tour.scenes}
    record = scene_record(by_name["scene_900001"], tour)
    expected = {"scene_900002": 0.0, "scene_900003": 90.0}
    assert record["link_yaw"] == expected, f"Got {record['link_yaw']}"
    assert set(record["link_yaw"]) <= set(record["links"]), "only linked scenes"


def test_scene_record_link_yaw_skips_scenes_outside_florya(
    scenes: list[Scene],
) -> None:
    tour = classify_tour(scenes)
    names = {s.name for s in tour.scenes}
    for scene in tour.scenes:
        yaws = scene_record(scene, tour)["link_yaw"]
        assert set(yaws) <= names, f"{scene.name}: {yaws}"
        assert all(0.0 <= v < 360.0 for v in yaws.values()), yaws
