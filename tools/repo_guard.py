"""Block copyrighted tour data and heavy binaries from entering the repository.

Used by pre-commit (receives staged file names) and CI (no args -> checks every
tracked file). See docs/data-policy.md.
"""

import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_BYTES = 1_000_000
FORBIDDEN_PREFIXES = ("data/",)
BINARY_SUFFIXES = frozenset(
    {
        ".jpg", ".jpeg", ".png", ".webp", ".avif", ".tif", ".tiff",
        ".glb", ".gltf", ".ply", ".obj", ".mvs", ".dmap", ".ktx2", ".bin",
        ".db", ".npz", ".npy", ".pt", ".onnx", ".zip",
    }
)  # fmt: skip
# Small, hand-made assets are allowed here (still subject to MAX_BYTES).
BINARY_ALLOWED_PREFIXES = (
    "packages/contracts/fixtures/",
    "apps/web/public/",
    "docs/assets/",
)
# Next.js metadata images must sit in the app root, not under public/.
APP_ICON_DIR = "apps/web/src/app/"
APP_ICON_STEMS = frozenset({"icon", "apple-icon", "opengraph-image", "twitter-image"})
SIZE_EXEMPT = frozenset({"uv.lock", "pnpm-lock.yaml"})


def _binary_allowed(path: str) -> bool:
    if path.startswith(BINARY_ALLOWED_PREFIXES):
        return True
    pure = PurePosixPath(path)
    return f"{pure.parent}/" == APP_ICON_DIR and pure.stem in APP_ICON_STEMS


@dataclass(frozen=True, slots=True)
class Violation:
    path: str
    reason: str


def check_paths(paths: Iterable[str], root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for raw in paths:
        path = PurePosixPath(raw).as_posix()
        if path.startswith(FORBIDDEN_PREFIXES):
            violations.append(Violation(path, "data/ must never be committed"))
            continue
        suffix = PurePosixPath(path).suffix.lower()
        if suffix in BINARY_SUFFIXES and not _binary_allowed(path):
            violations.append(Violation(path, f"binary {suffix} outside allowed dirs"))
        file = root / path
        if path not in SIZE_EXEMPT and file.is_file():
            size = file.stat().st_size
            if size > MAX_BYTES:
                violations.append(Violation(path, f"{size} bytes > {MAX_BYTES}"))
    return violations


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout.decode()
    return [p for p in out.split("\0") if p]


def main(argv: Sequence[str]) -> int:
    root = Path.cwd()
    paths = list(argv) if argv else tracked_files(root)
    violations = check_paths(paths, root)
    for v in violations:
        print(f"repo-guard: {v.path}: {v.reason}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
