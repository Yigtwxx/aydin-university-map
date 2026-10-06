"""Panorama descriptions with Gemini (vision inference; free tier, rate-limited).

Each scene's four horizontal cube faces are tiled into one 2x2 JPEG and sent
with the tour label, and the structured answer is appended to a JSONL file
keyed by scene and prompt version, so the job resumes after interruptions or
daily quota limits.
"""

import io
import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel, Field

PROMPT_VERSION = "vision_v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
VISION_MODEL = "gemini-3.5-flash-lite"
MOSAIC_FACES = ("f", "r", "b", "l")  # top-left, top-right, bottom-left, bottom-right
TILE_PX = 512


class SceneDescription(BaseModel):
    landmarks: list[str] = Field(default_factory=list, max_length=8)
    signage_text: list[str] = Field(default_factory=list, max_length=8)
    accessibility: list[str] = Field(default_factory=list)
    description_tr: str
    description_en: str
    indoor: bool


@dataclass(frozen=True, slots=True)
class VisionJob:
    scene: str
    label_tr: str
    label_en: str
    area_tr: str


def mosaic_jpeg(tiles_dir: Path, scene: str, tile_px: int = TILE_PX) -> bytes:
    """The four horizontal faces as one 2x2 JPEG (``tile_px`` per face)."""
    grid = Image.new("RGB", (tile_px * 2, tile_px * 2))
    for i, face in enumerate(MOSAIC_FACES):
        with Image.open(tiles_dir / scene / f"{face}.jpg") as img:
            tile = img.convert("RGB").resize(
                (tile_px, tile_px), Image.Resampling.LANCZOS
            )
        grid.paste(tile, ((i % 2) * tile_px, (i // 2) * tile_px))
    out = io.BytesIO()
    grid.save(out, format="JPEG", quality=85)
    return out.getvalue()


def prompt_for(job: VisionJob) -> str:
    return PROMPT_PATH.read_text("utf-8").format(
        label_tr=job.label_tr, label_en=job.label_en, area_tr=job.area_tr
    )


def done_scenes(jsonl: Path) -> set[str]:
    if not jsonl.is_file():
        return set()
    done: set[str] = set()
    for line in jsonl.read_text("utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if record.get("prompt_version") == PROMPT_VERSION:
                done.add(record["scene"])
    return done


def jobs_from_scenes(scenes: Iterable[Mapping[str, Any]]) -> list[VisionJob]:
    return [
        VisionJob(
            scene=s["name"],
            label_tr=s["label"]["tr"],
            label_en=s["label"]["en"],
            area_tr=s["area"]["tr"],
        )
        for s in scenes
    ]


def describe_all(
    jobs: list[VisionJob],
    tiles_dir: Path,
    jsonl: Path,
    api_key: str,
    rpm: float = 10.0,
    max_calls: int | None = None,
    progress: Callable[[str], None] = print,
) -> int:
    """Describe every job not yet in ``jsonl``; returns the number of new records."""
    from google import genai
    from google.genai import errors, types
    from tenacity import (
        retry,
        retry_if_exception,
        stop_after_attempt,
        wait_exponential,
    )

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=SceneDescription.model_json_schema(),
        temperature=0.2,
    )

    def retryable(exc: BaseException) -> bool:
        return isinstance(exc, errors.APIError) and exc.code in (429, 500, 503)

    @retry(
        retry=retry_if_exception(retryable),
        wait=wait_exponential(multiplier=8, min=8, max=120),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    def call(job: VisionJob) -> SceneDescription:
        response = client.models.generate_content(
            model=VISION_MODEL,
            contents=[
                types.Part.from_bytes(
                    data=mosaic_jpeg(tiles_dir, job.scene), mime_type="image/jpeg"
                ),
                prompt_for(job),
            ],
            config=config,
        )
        return SceneDescription.model_validate_json(response.text or "{}")

    done = done_scenes(jsonl)
    todo = [j for j in jobs if j.scene not in done]
    if max_calls is not None:
        todo = todo[:max_calls]
    progress(f"vision: {len(todo)} scenes to describe ({len(done)} done)")
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    interval = 60.0 / rpm
    written = 0
    with jsonl.open("a", encoding="utf-8") as out:
        for job in todo:
            started = time.monotonic()
            description = call(job)
            record = {
                "scene": job.scene,
                "prompt_version": PROMPT_VERSION,
                "model": VISION_MODEL,
                **description.model_dump(),
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            written += 1
            if written % 20 == 0:
                progress(f"vision: {written}/{len(todo)}")
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
    return written
