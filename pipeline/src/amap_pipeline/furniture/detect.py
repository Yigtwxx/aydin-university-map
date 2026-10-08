"""Find street furniture in the panoramas with an open-vocabulary detector.

OWLv2 (pretrained, inference only) looks at a ring of rectilinear views per
panorama for text queries ("a bench", "a planter box"…). Each box is kept as
angles in the panorama (``ath`` of its centre and sides, ``atv`` of its
bottom): angles do not depend on the pose, so the detections stay valid while
the survey corrects where panoramas stand. ``locate`` turns them into map
positions later.

The detector proposes; people (or a reviewing agent) dispose: every candidate
is checked on its crop before it reaches ``configs/furniture.toml``.
"""

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from amap_pipeline.look.camera import rig_angles
from amap_pipeline.look.render import ByteImage, View, render_view

DEFAULT_MODEL = "google/owlv2-base-patch16-ensemble"
QUERIES: dict[str, str] = {
    "bench": "a park bench",
    "planter": "a large plant pot or planter box",
    "bollard": "a short bollard post",
    "bin": "a trash can",
    "lamp": "a street lamp post",
    "stairs": "outdoor stairs",
    "railing": "a metal handrail",
    "table": "an outdoor cafe table",
    "chair": "an outdoor chair",
    "umbrella": "a patio umbrella",
    "bike_rack": "a bicycle rack",
}
# Bigger things around the campus that make a place recognisable.
LANDMARK_QUERIES: dict[str, str] = {
    "flagpole": "a tall flagpole with a flag",
    "booth": "a small security booth",
    "sign": "a large information sign board",
    "monument": "a stone monument",
    "tree": "a tree",
}
QUERY_SETS: dict[str, dict[str, str]] = {
    "street": QUERIES,
    "landmarks": LANDMARK_QUERIES,
}
VIEW_ATHS = tuple(float(a) for a in range(0, 360, 45))
VIEW_PITCH_DEG = 18.0
VIEW_FOV_DEG = 70.0
VIEW_PX = 960


@dataclass(frozen=True, slots=True)
class Detection:
    scene: str
    kind: str
    score: float
    ath_deg: float  # bottom-centre of the box
    atv_bottom_deg: float  # positive = below the horizon
    atv_top_deg: float
    ath_left_deg: float
    ath_right_deg: float
    view_ath_deg: float
    box_px: tuple[float, float, float, float]  # x0, y0, x1, y1 in the view


def view_for(ath: float) -> View:
    return View(ath, VIEW_PITCH_DEG, VIEW_FOV_DEG, VIEW_PX, VIEW_PX)


def box_angles(
    view: View, box: tuple[float, float, float, float]
) -> tuple[float, float, float, float, float]:
    """(ath centre, atv bottom, atv top, ath left, ath right) of a box."""
    right, down, forward = view.axes()
    f = view.focal_px
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2.0

    def ray(u: float, v: float) -> np.ndarray:
        d = (
            (u - view.width / 2.0) / f * right
            + (v - view.height / 2.0) / f * down
            + forward
        )
        return d / np.linalg.norm(d)

    pts = np.stack([ray(cx, y1), ray(cx, y0), ray(x0, y1), ray(x1, y1)])
    ath, atv = rig_angles(pts)
    return (
        float(ath[0]),
        float(atv[0]),
        float(atv[1]),
        float(ath[2]),
        float(ath[3]),
    )


class Detector:
    """OWLv2 on the best device (CUDA, then MPS, then CPU)."""

    def __init__(
        self,
        model_id: str | None = None,
        threshold: float = 0.18,
        queries: dict[str, str] | None = None,
    ) -> None:
        from amap_pipeline.device import select_device

        self.device = select_device()
        import torch  # pyright: ignore[reportMissingImports]  # `detect` extra
        from transformers import (  # pyright: ignore[reportMissingImports]
            Owlv2ForObjectDetection,
            Owlv2Processor,
        )

        name = model_id or os.environ.get("AMAP_DETECT_MODEL", DEFAULT_MODEL)
        self.torch = torch
        self.processor = Owlv2Processor.from_pretrained(name)
        self.model = Owlv2ForObjectDetection.from_pretrained(name).to(self.device)  # pyright: ignore[reportArgumentType]
        self.model.eval()
        self.threshold = threshold
        chosen = queries or QUERIES
        self.kinds = list(chosen)
        self.texts = [[chosen[k] for k in self.kinds]]

    def boxes(
        self, image: ByteImage
    ) -> list[tuple[str, float, tuple[float, float, float, float]]]:
        torch = self.torch
        inputs = self.processor(images=image, text=self.texts, return_tensors="pt")  # pyright: ignore[reportCallIssue]
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self.model(**inputs)
        size = max(image.shape[0], image.shape[1])
        target = [(size, size)]
        result = self.processor.post_process_grounded_object_detection(
            outputs=outputs, threshold=self.threshold, target_sizes=target
        )[0]
        out: list[tuple[str, float, tuple[float, float, float, float]]] = []
        for score, label, box in zip(
            result["scores"].tolist(),
            result["labels"].tolist(),
            result["boxes"].tolist(),
            strict=True,
        ):
            x0, y0, x1, y1 = (float(v) for v in box)
            out.append((self.kinds[int(label)], float(score), (x0, y0, x1, y1)))
        return nms(out)


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def nms(
    boxes: Iterable[tuple[str, float, tuple[float, float, float, float]]],
    threshold: float = 0.5,
) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """Per kind, keep the best of boxes that overlap more than ``threshold``."""
    kept: list[tuple[str, float, tuple[float, float, float, float]]] = []
    for kind, score, box in sorted(boxes, key=lambda b: -b[1]):
        if any(k == kind and iou(box, b) > threshold for k, _, b in kept):
            continue
        kept.append((kind, score, box))
    return kept


def detect_scene(
    detector: Detector, faces: Mapping[str, ByteImage], scene: str
) -> list[Detection]:
    found: list[Detection] = []
    for ath in VIEW_ATHS:
        view = view_for(ath)
        image = render_view(faces, view)
        for kind, score, box in detector.boxes(image):
            # A box cut by the view's edge is seen whole in the next view.
            if box[0] < 4 or box[2] > view.width - 4:
                continue
            c, bottom, top, left, right = box_angles(view, box)
            found.append(
                Detection(
                    scene=scene,
                    kind=kind,
                    score=round(score, 3),
                    ath_deg=round(c, 2),
                    atv_bottom_deg=round(bottom, 2),
                    atv_top_deg=round(top, 2),
                    ath_left_deg=round(left, 2),
                    ath_right_deg=round(right, 2),
                    view_ath_deg=ath,
                    box_px=(
                        round(box[0], 1),
                        round(box[1], 1),
                        round(box[2], 1),
                        round(box[3], 1),
                    ),
                )
            )
    return found


def write_detections(path: Path, detections: Iterable[Detection]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as fh:
        for d in detections:
            fh.write(json.dumps(asdict(d)) + "\n")
            count += 1
    return count


def read_detections(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]
