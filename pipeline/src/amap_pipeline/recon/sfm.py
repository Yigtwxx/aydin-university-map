"""Structure-from-Motion over cube-face panoramas with pycolmap (CPU, no training).

Each panorama is one rig frame of up to 6 pinhole sensors (see ``cubemap``).
Image pairs come from the tour's walkable links, which keeps matching fast and
avoids false matches between look-alike places on the campus.

Workspace layout (``data/recon/<run>/``)::

    images/<face>/<scene>.jpg     staged faces (symlink or resized copy)
    masks/<face>/<scene>.jpg.png  feature masks (black = ignore)
    rig_config.json  pairs.txt  database.db  sparse/<model>/  report.json
"""

import json
import os
import shutil
import subprocess
import time
import tomllib
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from amap_pipeline.recon.cubemap import FACES, TRANSFORMS, rig_config

EXTRACTORS = {
    "sift": "SIFT",
    "aliked_n16rot": "ALIKED_N16ROT",
    "aliked_n32": "ALIKED_N32",
}
MATCHERS = {
    "sift_bruteforce": "SIFT_BRUTEFORCE",
    "sift_lightglue": "SIFT_LIGHTGLUE",
    "aliked_lightglue": "ALIKED_LIGHTGLUE",
}


@dataclass(frozen=True, slots=True)
class SfmConfig:
    set: str
    run: str
    faces: tuple[str, ...] = ("f", "r", "b", "l", "d")
    face_px: int = 1300
    pair_hops: int = 2
    nadir_mask_radius: float = 0.18
    max_num_features: int = 8192
    estimate_affine_shape: bool = False
    domain_size_pooling: bool = False
    mapper: str = "incremental"
    # Incremental mapper thresholds (COLMAP defaults: 100 / 10 / 30). Wide
    # baselines between tour panoramas give 40-120 verified inliers per pair, so
    # the default initialisation threshold rejects whole clusters.
    init_min_num_inliers: int = 100
    init_min_tri_angle: float = 16.0
    min_model_size: int = 10
    abs_pose_min_num_inliers: int = 30
    # Features/matcher: "sift" | "aliked_n16rot" | "aliked_n32" and
    # "sift_bruteforce" | "sift_lightglue" | "aliked_lightglue" (pretrained
    # inference via ONNX; no training).
    extractor: str = "sift"
    matcher: str = "sift_bruteforce"
    learned_max_features: int = 4096

    @property
    def uses_onnx(self) -> bool:
        """Learned features need the ONNX-enabled COLMAP CLI (pip pycolmap lacks it)."""
        return self.extractor != "sift" or self.matcher != "sift_bruteforce"

    transforms: dict[str, str] = field(
        default_factory=lambda: dict.fromkeys(FACES, "id")
    )

    @classmethod
    def from_toml(cls, path: Path) -> "SfmConfig":
        raw = tomllib.loads(path.read_text(encoding="utf-8"))["sfm"]
        if "faces" in raw:
            raw["faces"] = tuple(raw["faces"])
        cfg = cls(**raw)
        unknown = set(cfg.faces) - set(FACES)
        if unknown or "f" not in cfg.faces:
            raise ValueError(f"faces must include 'f' and be a subset of {FACES}")
        if cfg.mapper not in {"incremental", "global"}:
            raise ValueError(f"unknown mapper {cfg.mapper!r}")
        if cfg.extractor not in EXTRACTORS or cfg.matcher not in MATCHERS:
            raise ValueError(f"unknown extractor/matcher {cfg.extractor}/{cfg.matcher}")
        if cfg.extractor.split("_")[0] != cfg.matcher.split("_")[0]:
            raise ValueError("matcher must match the extractor's descriptor family")
        return cfg


def image_name(face: str, scene: str) -> str:
    return f"{face}/{scene}.jpg"


def scene_of(name: str) -> str:
    """``"r/scene_1.jpg"`` -> ``"scene_1"``."""
    return name.split("/", 1)[1].removesuffix(".jpg")


def stage_images(
    scenes: Sequence[str], tiles_dir: Path, images_dir: Path, cfg: SfmConfig
) -> list[str]:
    """Place faces under ``images/<face>/``; resize/transform only when needed."""
    names: list[str] = []
    for scene in scenes:
        for face in cfg.faces:
            src = tiles_dir / scene / f"{face}.jpg"
            dst = images_dir / image_name(face, scene)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            transform = cfg.transforms.get(face, "id")
            with Image.open(src) as img:
                needs_resize = img.size != (cfg.face_px, cfg.face_px)
                if transform == "id" and not needs_resize:
                    os.symlink(src.resolve(), dst)
                else:
                    _write_normalised(img, dst, cfg.face_px, transform)
            names.append(image_name(face, scene))
    return names


def _write_normalised(img: Image.Image, dst: Path, size: int, transform: str) -> None:
    rgb = img.convert("RGB")
    if rgb.size != (size, size):
        rgb = rgb.resize((size, size), Image.Resampling.LANCZOS)
    if transform != "id":
        array = TRANSFORMS[transform](np.asarray(rgb, dtype=np.float64))
        rgb = Image.fromarray(np.ascontiguousarray(array).astype(np.uint8))
    rgb.save(dst, quality=95)


def write_masks(scenes: Sequence[str], masks_dir: Path, cfg: SfmConfig) -> list[Path]:
    """Mask the patched nadir (centre of the down face); other faces stay open."""
    written: list[Path] = []
    size = cfg.face_px
    radius = cfg.nadir_mask_radius * size
    open_mask = Image.new("L", (size, size), 255)
    nadir_mask = open_mask.copy()
    ImageDraw.Draw(nadir_mask).ellipse(
        (size / 2 - radius, size / 2 - radius, size / 2 + radius, size / 2 + radius),
        fill=0,
    )
    for scene in scenes:
        for face in cfg.faces:
            path = masks_dir / f"{image_name(face, scene)}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            (nadir_mask if face == "d" else open_mask).save(path)
            written.append(path)
    return written


def scene_pairs(
    scenes: Sequence[str], adjacency: Mapping[str, set[str]], hops: int
) -> list[tuple[str, str]]:
    """Unordered scene pairs within ``hops`` links, inside the scene set only."""
    members = set(scenes)
    pairs: set[tuple[str, str]] = set()
    for start in scenes:
        depth = {start: 0}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            if depth[node] == hops:
                continue
            for nxt in adjacency.get(node, set()) & members:
                if nxt not in depth:
                    depth[nxt] = depth[node] + 1
                    queue.append(nxt)
        for other in depth:
            if other != start:
                a, b = sorted((start, other))
                pairs.add((a, b))
    return sorted(pairs)


def write_pairs(
    path: Path, pairs: Sequence[tuple[str, str]], faces: Sequence[str]
) -> int:
    lines = [
        f"{image_name(fa, a)} {image_name(fb, b)}"
        for a, b in pairs
        for fa in faces
        for fb in faces
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def write_workspace_rig(path: Path, cfg: SfmConfig) -> None:
    """Rig config restricted to the faces actually used in this run."""
    config = rig_config(cfg.face_px)
    cameras = config[0]["cameras"]
    assert isinstance(cameras, list)
    config[0]["cameras"] = [c for c in cameras if c["image_prefix"][0] in cfg.faces]
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


@dataclass(slots=True)
class StageTimer:
    seconds: dict[str, float] = field(default_factory=dict)
    _start: float = field(default_factory=time.perf_counter)

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.seconds[name] = round(now - self._start, 1)
        self._start = now


def summarise_models(models: Mapping[int, Any], cfg: SfmConfig) -> list[dict[str, Any]]:
    """Per-model registration stats (works on pycolmap Reconstruction objects)."""
    summaries: list[dict[str, Any]] = []
    for index, rec in sorted(models.items()):
        faces_per_scene: dict[str, int] = {}
        for image_id in rec.reg_image_ids():
            scene = scene_of(rec.image(image_id).name)
            faces_per_scene[scene] = faces_per_scene.get(scene, 0) + 1
        full = sorted(s for s, n in faces_per_scene.items() if n == len(cfg.faces))
        summaries.append(
            {
                "model": index,
                "reg_frames": rec.num_reg_frames(),
                "reg_images": rec.num_reg_images(),
                "points3D": rec.num_points3D(),
                "mean_reproj_px": round(rec.compute_mean_reprojection_error(), 3),
                "mean_track_length": round(rec.compute_mean_track_length(), 2),
                "scenes": sorted(faces_per_scene),
                "scenes_all_faces": full,
            }
        )
    summaries.sort(key=lambda m: -m["reg_frames"])
    return summaries


def _extract_and_match(
    cfg: SfmConfig,
    scenes: Sequence[str],
    pairs: Sequence[tuple[str, str]],
    tiles_dir: Path,
    workspace: Path,
    timer: StageTimer,
) -> None:
    """Stage images and masks, extract SIFT, apply the rig and match pairs."""
    import pycolmap

    images_dir, masks_dir = workspace / "images", workspace / "masks"
    database = workspace / "database.db"
    names = stage_images(scenes, tiles_dir, images_dir, cfg)
    write_masks(scenes, masks_dir, cfg)
    write_pairs(workspace / "pairs.txt", pairs, cfg.faces)
    write_workspace_rig(workspace / "rig_config.json", cfg)
    timer.lap("stage")
    if cfg.uses_onnx:
        _extract_and_match_cli(cfg, names, workspace, timer)
        return

    focal = cfg.face_px / 2.0
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "SIMPLE_PINHOLE"
    reader.camera_params = f"{focal},{focal},{focal}"
    reader.mask_path = str(masks_dir)
    extraction = pycolmap.FeatureExtractionOptions()
    extraction.type = getattr(pycolmap.FeatureExtractorType, EXTRACTORS[cfg.extractor])
    extraction.sift.max_num_features = cfg.max_num_features
    extraction.sift.estimate_affine_shape = cfg.estimate_affine_shape
    extraction.sift.domain_size_pooling = cfg.domain_size_pooling
    pycolmap.extract_features(
        database,
        images_dir,
        image_names=names,
        camera_mode=pycolmap.CameraMode.PER_FOLDER,
        reader_options=reader,
        extraction_options=extraction,
    )
    timer.lap("extract")

    db = pycolmap.Database.open(database)
    try:
        pycolmap.apply_rig_config(
            pycolmap.read_rig_config(workspace / "rig_config.json"), db
        )
    finally:
        db.close()
    timer.lap("rig")

    matching = pycolmap.FeatureMatchingOptions()
    matching.type = getattr(pycolmap.FeatureMatcherType, MATCHERS[cfg.matcher])
    matching.rig_verification = True
    matching.skip_image_pairs_in_same_frame = True
    pairing = pycolmap.ImportedPairingOptions()
    pairing.match_list_path = str(workspace / "pairs.txt")
    pycolmap.match_image_pairs(
        database, matching_options=matching, pairing_options=pairing
    )
    timer.lap("match")


class ColmapError(RuntimeError):
    """A COLMAP CLI step failed; the message carries the tail of its log."""


def _colmap(*args: str) -> None:
    """Run the COLMAP CLI (``$COLMAP_BIN`` or ``colmap`` on PATH)."""
    binary = os.environ.get("COLMAP_BIN", "colmap")
    proc = subprocess.run([binary, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).splitlines()[-25:])
        raise ColmapError(f"colmap {args[0]} exited with {proc.returncode}:\n{tail}")


def _extract_and_match_cli(
    cfg: SfmConfig, names: Sequence[str], workspace: Path, timer: StageTimer
) -> None:
    database = str(workspace / "database.db")
    image_list = workspace / "image_list.txt"
    image_list.write_text("\n".join(names) + "\n", encoding="utf-8")
    focal = cfg.face_px / 2.0
    family = "Aliked" if cfg.extractor.startswith("aliked") else "Sift"
    _colmap(
        "feature_extractor",
        "--database_path", database,
        "--image_path", str(workspace / "images"),
        "--image_list_path", str(image_list),
        "--ImageReader.single_camera_per_folder", "1",
        "--ImageReader.camera_model", "SIMPLE_PINHOLE",
        "--ImageReader.camera_params", f"{focal},{focal},{focal}",
        "--ImageReader.mask_path", str(workspace / "masks"),
        "--FeatureExtraction.type", EXTRACTORS[cfg.extractor],
        f"--{family}Extraction.max_num_features",
        str(cfg.learned_max_features if family == "Aliked" else cfg.max_num_features),
    )  # fmt: skip
    timer.lap("extract")
    _colmap(
        "rig_configurator",
        "--database_path", database,
        "--rig_config_path", str(workspace / "rig_config.json"),
    )  # fmt: skip
    timer.lap("rig")
    _colmap(
        "matches_importer",
        "--database_path", database,
        "--match_list_path", str(workspace / "pairs.txt"),
        "--match_type", "pairs",
        "--FeatureMatching.type", MATCHERS[cfg.matcher],
        "--FeatureMatching.rig_verification", "1",
        "--FeatureMatching.skip_image_pairs_in_same_frame", "1",
    )  # fmt: skip
    timer.lap("match")


def run_sfm(
    cfg: SfmConfig,
    scenes: Sequence[str],
    adjacency: Mapping[str, set[str]],
    tiles_dir: Path,
    workspace: Path,
    map_only: bool = False,
) -> dict[str, Any]:
    """Run the sparse reconstruction and return (and write) a report.

    ``map_only`` reuses the existing database (features + matches) and only
    re-runs the mapper, e.g. after tuning mapper thresholds.
    """
    import pycolmap

    timer = StageTimer()
    images_dir = workspace / "images"
    database = workspace / "database.db"
    sparse = workspace / "sparse"
    if map_only and not database.is_file():
        raise FileNotFoundError(f"--map-only needs an existing {database}")
    shutil.rmtree(sparse, ignore_errors=True)
    sparse.mkdir(parents=True)
    pairs = scene_pairs(scenes, adjacency, cfg.pair_hops)
    num_image_pairs = len(pairs) * len(cfg.faces) ** 2
    if not map_only:
        database.unlink(missing_ok=True)
        _extract_and_match(cfg, scenes, pairs, tiles_dir, workspace, timer)

    if cfg.mapper == "global":
        models = pycolmap.global_mapping(database, images_dir, sparse)
    else:
        options = pycolmap.IncrementalPipelineOptions()
        options.ba_refine_sensor_from_rig = False
        options.ba_refine_focal_length = False
        options.ba_refine_principal_point = False
        options.ba_refine_extra_params = False
        options.min_model_size = cfg.min_model_size
        options.mapper.init_min_num_inliers = cfg.init_min_num_inliers
        options.mapper.init_min_tri_angle = cfg.init_min_tri_angle
        options.mapper.abs_pose_min_num_inliers = cfg.abs_pose_min_num_inliers
        models = pycolmap.incremental_mapping(database, images_dir, sparse, options)
    timer.lap("map")

    summaries = summarise_models(models, cfg)
    largest = summaries[0] if summaries else None
    report: dict[str, Any] = {
        "config": asdict(cfg),
        "scenes": len(scenes),
        "scene_pairs": len(pairs),
        "image_pairs": num_image_pairs,
        "models": summaries,
        "largest_model_scenes_all_faces": len(largest["scenes_all_faces"])
        if largest
        else 0,
        "seconds": timer.seconds,
    }
    (workspace / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report
