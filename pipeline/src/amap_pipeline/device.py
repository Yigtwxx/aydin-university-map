"""Torch device for pretrained inference: CUDA, then Apple MPS, then CPU."""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch  # pyright: ignore[reportMissingImports]  # `learned` extra


def configure_torch_env() -> None:
    """Call before importing torch: ops without an MPS kernel fall back to CPU."""
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def select_device() -> "torch.device":
    configure_torch_env()
    import torch  # pyright: ignore[reportMissingImports]  # `learned` extra

    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
