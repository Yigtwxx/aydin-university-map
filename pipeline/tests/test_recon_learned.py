"""Database plumbing of the LightGlue matcher (no torch, no real tour data)."""

import sqlite3
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from amap_pipeline.recon.learned import (
    MAX_NUM_IMAGES,
    keep_unmasked,
    pair_id,
    read_image_pairs,
    sql_image_ids,
    sql_matched_pairs,
    sql_write_keypoints,
    sql_write_matches,
)


@pytest.fixture
def colmap_db() -> sqlite3.Connection:
    """The three COLMAP tables the worker touches, as in COLMAP 4.x."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE images (image_id INTEGER PRIMARY KEY, name TEXT UNIQUE,
                             camera_id INTEGER);
        CREATE TABLE keypoints (image_id INTEGER PRIMARY KEY, rows INTEGER,
                                cols INTEGER, data BLOB);
        CREATE TABLE matches (pair_id INTEGER PRIMARY KEY, rows INTEGER,
                              cols INTEGER, data BLOB);
        INSERT INTO images VALUES (1, 'f/scene_a.jpg', 1), (2, 'r/scene_b.jpg', 2);
        """
    )
    return conn


def test_pair_id_is_order_independent_and_matches_colmap() -> None:
    assert pair_id(5, 2) == pair_id(2, 5), "pair id must not depend on order"
    assert pair_id(2, 5) == 2 * MAX_NUM_IMAGES + 5, "COLMAP: id1 * kMax + id2"


def test_sql_write_keypoints_shifts_to_colmap_origin(
    colmap_db: sqlite3.Connection,
) -> None:
    sql_write_keypoints(colmap_db, 1, np.array([[0.0, 0.0], [10.0, 5.0]], np.float32))
    rows, cols, blob = colmap_db.execute(
        "SELECT rows, cols, data FROM keypoints WHERE image_id = 1"
    ).fetchone()
    stored = np.frombuffer(blob, np.float32).reshape(rows, cols)
    assert (rows, cols) == (2, 2), f"expected 2x2 keypoints, got {rows}x{cols}"
    assert np.allclose(stored, [[0.5, 0.5], [10.5, 5.5]]), "keypoints need +0.5"


def test_sql_write_matches_swaps_columns_for_descending_ids(
    colmap_db: sqlite3.Connection,
) -> None:
    sql_write_matches(colmap_db, 2, 1, np.array([[7, 3], [8, 4]], np.uint32))
    rows, blob = colmap_db.execute(
        "SELECT rows, data FROM matches WHERE pair_id = ?", (pair_id(1, 2),)
    ).fetchone()
    stored = np.frombuffer(blob, np.uint32).reshape(rows, 2)
    assert stored.tolist() == [[3, 7], [4, 8]], "image 1's indices come first"


def test_sql_matched_pairs_lists_written_pairs(colmap_db: sqlite3.Connection) -> None:
    sql_write_matches(colmap_db, 1, 2, np.zeros((0, 2), np.uint32))
    assert sql_matched_pairs(colmap_db) == {pair_id(1, 2)}, "empty matches count"
    assert sql_image_ids(colmap_db) == {"f/scene_a.jpg": 1, "r/scene_b.jpg": 2}


def test_keep_unmasked_drops_keypoints_on_black_pixels(tmp_path: Path) -> None:
    mask = Image.new("L", (10, 10), 255)
    mask.putpixel((2, 3), 0)
    path = tmp_path / "mask.png"
    mask.save(path)
    keep = keep_unmasked(np.array([[2.0, 3.0], [5.0, 5.0]], np.float32), path)
    assert keep.tolist() == [False, True], f"masked point must go, got {keep}"


def test_keep_unmasked_without_mask_keeps_all() -> None:
    keep = keep_unmasked(np.zeros((3, 2), np.float32), None)
    assert keep.all(), "no mask means every keypoint stays"


def test_read_image_pairs_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "pairs.txt"
    path.write_text("f/a.jpg r/b.jpg\n\nl/a.jpg b/b.jpg\n", encoding="utf-8")
    assert read_image_pairs(path) == [
        ("f/a.jpg", "r/b.jpg"),
        ("l/a.jpg", "b/b.jpg"),
    ], "one pair per non-empty line"
