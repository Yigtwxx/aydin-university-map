"""Pretrained ALIKED/DISK + LightGlue features and matches for COLMAP.

Inference only (no training), on CUDA, MPS or CPU (see ``amap_pipeline.device``).
The flow follows hloc: images and the rig go into the COLMAP database first,
then keypoints and raw matches are written directly, and pycolmap's geometric
verification (with rig constraints) turns them into two-view geometries for
the usual incremental mapper. Descriptors never enter the database.

torch and pycolmap each ship their own OpenMP runtime and abort when loaded
into one process, so the torch part runs in a worker subprocess
(``python -m amap_pipeline.recon.learned``) that writes the database with
plain SQLite; the parent keeps pycolmap for import, rig and verification.

Features are cached per image under ``features/<extractor>/<face>/<scene>.npz``
and pairs already in the database are skipped, so an interrupted run resumes.
"""

import argparse
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from amap_pipeline.device import configure_torch_env, select_device

Progress = Callable[[str], None]

TORCH_EXTRACTORS = frozenset({"aliked_n16", "disk"})
# LightGlue needs keypoints on both sides; nearly empty faces (a fully masked
# or featureless face) cannot produce a verifiable pair anyway.
MIN_KEYPOINTS = 16
# COLMAP's kMaxNumImages: pair ids are image_id1 * this + image_id2.
MAX_NUM_IMAGES = 2147483647
COMMIT_EVERY = 200


@dataclass(frozen=True, slots=True)
class LearnedOptions:
    extractor: str = "aliked_n16"
    max_keypoints: int = 4096
    log_every: int = 500


@dataclass(frozen=True, slots=True)
class Features:
    keypoints: NDArray[np.float32]  # N x 2, pixels, origin at the first pixel centre
    descriptors: NDArray[np.float16]  # N x D


def _print(message: str) -> None:
    print(message, flush=True)


def pair_id(image_id1: int, image_id2: int) -> int:
    first, second = sorted((image_id1, image_id2))
    return first * MAX_NUM_IMAGES + second


def read_image_pairs(path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            pairs.append((parts[0], parts[1]))
    return pairs


# --- SQLite access (worker side; no pycolmap) --------------------------------


def sql_image_ids(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        name: int(i) for i, name in conn.execute("SELECT image_id, name FROM images")
    }


def sql_write_keypoints(
    conn: sqlite3.Connection, image_id: int, keypoints: NDArray[np.float32]
) -> None:
    # COLMAP puts the origin at the image corner, detectors at the centre of
    # the first pixel.
    data = np.ascontiguousarray(keypoints + 0.5, dtype=np.float32)
    conn.execute(
        "INSERT OR REPLACE INTO keypoints (image_id, rows, cols, data) "
        "VALUES (?, ?, ?, ?)",
        (image_id, data.shape[0], 2, data.tobytes()),
    )


def sql_matched_pairs(conn: sqlite3.Connection) -> set[int]:
    return {int(p) for (p,) in conn.execute("SELECT pair_id FROM matches")}


def sql_write_matches(
    conn: sqlite3.Connection,
    image_id1: int,
    image_id2: int,
    matches: NDArray[np.uint32],
) -> None:
    """Store matches with the smaller image id first, as COLMAP expects."""
    if image_id1 > image_id2:
        matches = matches[:, ::-1]
    data = np.ascontiguousarray(matches, dtype=np.uint32).reshape(-1, 2)
    conn.execute(
        "INSERT OR REPLACE INTO matches (pair_id, rows, cols, data) "
        "VALUES (?, ?, ?, ?)",
        (pair_id(image_id1, image_id2), data.shape[0], 2, data.tobytes()),
    )


# --- Inference (worker side) --------------------------------------------------


def _load_rgb(path: Path) -> NDArray[np.float32]:
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0


def keep_unmasked(
    keypoints: NDArray[np.float32], mask_path: Path | None
) -> NDArray[np.bool_]:
    """Drop keypoints on black mask pixels (the patched nadir), like COLMAP does."""
    if mask_path is None or not mask_path.is_file():
        return np.ones(len(keypoints), dtype=bool)
    with Image.open(mask_path) as mask:
        values = np.asarray(mask.convert("L"))
    cols = np.clip(keypoints[:, 0].round().astype(int), 0, values.shape[1] - 1)
    rows = np.clip(keypoints[:, 1].round().astype(int), 0, values.shape[0] - 1)
    return values[rows, cols] > 0


class _Models:
    """Extractor and matcher on the selected device."""

    def __init__(self, options: LearnedOptions) -> None:
        configure_torch_env()
        import torch
        from kornia.feature import ALIKED, DISK, LightGlue

        self.torch = torch
        self.device = select_device()
        self.options = options
        if options.extractor == "aliked_n16":
            self.extractor: Any = ALIKED.from_pretrained(
                "aliked-n16",
                max_num_keypoints=options.max_keypoints,
                device=self.device,
            ).eval()
            self.matcher: Any = LightGlue(features="aliked").eval().to(self.device)
        elif options.extractor == "disk":
            self.extractor = DISK.from_pretrained("depth", device=self.device).eval()
            self.matcher = LightGlue(features="disk").eval().to(self.device)
        else:
            raise ValueError(f"unknown torch extractor {options.extractor!r}")

    def extract(self, rgb: NDArray[np.float32]) -> Features:
        torch = self.torch
        image = torch.from_numpy(rgb).permute(2, 0, 1)[None].to(self.device)
        with torch.inference_mode():
            if self.options.extractor == "disk":
                out = self.extractor(
                    image, n=self.options.max_keypoints, pad_if_not_divisible=True
                )[0]
            else:
                out = self.extractor(image)[0]
        return Features(
            keypoints=out.keypoints.float().cpu().numpy().astype(np.float32),
            descriptors=out.descriptors.float().cpu().numpy().astype(np.float16),
        )

    def match(
        self, a: Features, b: Features, size: tuple[int, int]
    ) -> NDArray[np.uint32]:
        if min(len(a.keypoints), len(b.keypoints)) < MIN_KEYPOINTS:
            return np.zeros((0, 2), dtype=np.uint32)
        torch = self.torch
        image_size = torch.tensor([[size[0], size[1]]], device=self.device)

        def side(f: Features) -> dict[str, Any]:
            return {
                "keypoints": torch.from_numpy(f.keypoints)[None].to(self.device),
                "descriptors": torch.from_numpy(f.descriptors.astype(np.float32))[
                    None
                ].to(self.device),
                "image_size": image_size,
            }

        with torch.inference_mode():
            out = self.matcher({"image0": side(a), "image1": side(b)})
        return out["matches"][0].cpu().numpy().astype(np.uint32)


def extract_features(
    names: Iterable[str],
    images_dir: Path,
    masks_dir: Path,
    cache_dir: Path,
    models: _Models,
    progress: Progress = _print,
) -> dict[str, Features]:
    """Features for every image, read from (or written to) the per-image cache."""
    names = list(names)
    feats: dict[str, Features] = {}
    start = time.perf_counter()
    computed = 0
    for name in names:
        cached = cache_dir / f"{name}.npz"
        if cached.is_file():
            with np.load(cached) as data:
                feats[name] = Features(data["keypoints"], data["descriptors"])
            continue
        raw = models.extract(_load_rgb(images_dir / name))
        keep = keep_unmasked(raw.keypoints, masks_dir / f"{name}.png")
        feats[name] = Features(raw.keypoints[keep], raw.descriptors[keep])
        cached.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            cached, keypoints=feats[name].keypoints, descriptors=feats[name].descriptors
        )
        computed += 1
        if computed % 50 == 0:
            rate = (time.perf_counter() - start) / computed
            progress(f"extract {len(feats)}/{len(names)} ({rate * 1000:.0f} ms/image)")
    return feats


def run_worker(
    workspace: Path,
    options: LearnedOptions,
    face_px: int,
    progress: Progress = _print,
) -> None:
    """Extract, then match every pair in ``pairs.txt`` missing from the database."""
    models = _Models(options)
    progress(f"device {models.device}, extractor {options.extractor}")
    conn = sqlite3.connect(workspace / "database.db")
    try:
        ids = sql_image_ids(conn)
        feats = extract_features(
            ids,
            workspace / "images",
            workspace / "masks",
            workspace / "features" / options.extractor,
            models,
            progress,
        )
        for name, image_id in ids.items():
            sql_write_keypoints(conn, image_id, feats[name].keypoints)
        conn.commit()
        progress("keypoints written")

        done = sql_matched_pairs(conn)
        todo = [
            (a, b)
            for a, b in read_image_pairs(workspace / "pairs.txt")
            if pair_id(ids[a], ids[b]) not in done
        ]
        progress(f"match {len(todo)} pairs ({len(done)} already in the database)")
        start = time.perf_counter()
        for i, (a, b) in enumerate(todo, 1):
            sql_write_matches(
                conn,
                ids[a],
                ids[b],
                models.match(feats[a], feats[b], (face_px, face_px)),
            )
            if i % COMMIT_EVERY == 0:
                conn.commit()
            if i % options.log_every == 0:
                rate = (time.perf_counter() - start) / i
                left_min = rate * (len(todo) - i) / 60
                progress(
                    f"match {i}/{len(todo)} "
                    f"({rate * 1000:.0f} ms/pair, ~{left_min:.0f} min left)"
                )
        conn.commit()
        progress("matches written")
    finally:
        conn.close()


# --- Orchestration (parent side; pycolmap) -------------------------------------


def populate_database(
    database: Path,
    images_dir: Path,
    names: Sequence[str],
    rig_config_path: Path,
    focal: float,
) -> None:
    """Register images (one camera per face folder) and the rig."""
    import pycolmap

    pycolmap.Database.open(database).close()  # creates the schema
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "SIMPLE_PINHOLE"
    reader.camera_params = f"{focal},{focal},{focal}"
    pycolmap.import_images(
        database,
        images_dir,
        camera_mode=pycolmap.CameraMode.PER_FOLDER,
        image_names=list(names),
        options=reader,
    )
    db = pycolmap.Database.open(database)
    try:
        pycolmap.apply_rig_config(pycolmap.read_rig_config(rig_config_path), db)
    finally:
        db.close()


def verify(database: Path) -> None:
    """Two-view geometries for every matched pair, rig constraints included."""
    import pycolmap

    verifier = pycolmap.GeometricVerifierOptions()
    verifier.rig_verification = True
    pycolmap.geometric_verification(database, verifier_options=verifier)


def extract_and_match(
    names: Sequence[str],
    workspace: Path,
    focal: float,
    face_px: int,
    options: LearnedOptions,
    progress: Progress = _print,
) -> dict[str, float]:
    """Fill ``workspace/database.db`` with learned keypoints and verified matches."""
    timings: dict[str, float] = {}
    tick = time.perf_counter()

    def lap(stage: str) -> None:
        nonlocal tick
        now = time.perf_counter()
        timings[stage] = round(now - tick, 1)
        tick = now
        progress(f"{stage} done in {timings[stage]:.0f} s")

    database = workspace / "database.db"
    if not database.is_file():
        populate_database(
            database, workspace / "images", names, workspace / "rig_config.json", focal
        )
    lap("rig")
    cmd = [
        sys.executable,
        "-m",
        "amap_pipeline.recon.learned",
        "--workspace", str(workspace),
        "--extractor", options.extractor,
        "--max-keypoints", str(options.max_keypoints),
        "--face-px", str(face_px),
    ]  # fmt: skip
    with subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line and "Warning" not in line and not line.startswith("  warnings."):
                progress(line)
    if proc.returncode != 0:
        raise RuntimeError(f"learned matching worker exited with {proc.returncode}")
    lap("extract_match")
    verify(database)
    lap("verify")
    return timings


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="LightGlue matching worker.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--extractor", default="aliked_n16")
    parser.add_argument("--max-keypoints", type=int, default=4096)
    parser.add_argument("--face-px", type=int, default=1300)
    args = parser.parse_args(argv)
    run_worker(
        args.workspace,
        LearnedOptions(extractor=args.extractor, max_keypoints=args.max_keypoints),
        args.face_px,
    )


if __name__ == "__main__":
    main()
