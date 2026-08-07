"""GPU / CUDA helpers (Spec §31)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GpuInfo:
    available: bool
    name: str | None = None
    vram_bytes: int | None = None
    cuda_version: str | None = None
    torch_version: str | None = None
    torch_cuda_available: bool = False
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "name": self.name,
            "vram_bytes": self.vram_bytes,
            "vram_gb": round(self.vram_bytes / (1024**3), 2) if self.vram_bytes else None,
            "cuda_version": self.cuda_version,
            "torch_version": self.torch_version,
            "torch_cuda_available": self.torch_cuda_available,
            "detail": self.detail,
        }


def probe_gpu() -> GpuInfo:
    try:
        import torch
    except ImportError:
        return GpuInfo(available=False, detail="torch not installed")

    info = GpuInfo(
        available=False,
        torch_version=getattr(torch, "__version__", None),
        torch_cuda_available=bool(torch.cuda.is_available()),
    )
    if not info.torch_cuda_available:
        info.detail = "torch.cuda.is_available() is False"
        return info

    try:
        idx = torch.cuda.current_device()
        props = torch.cuda.get_device_properties(idx)
        info.available = True
        info.name = props.name
        info.vram_bytes = int(props.total_memory)
        info.cuda_version = getattr(torch.version, "cuda", None)
    except Exception as exc:  # noqa: BLE001 — doctor must be resilient
        info.detail = f"cuda probe failed: {exc}"
    return info


def resolve_device(requested: str) -> str:
    """Map auto|cuda|cpu → device_map string."""
    requested = (requested or "auto").lower()
    if requested == "cpu":
        return "cpu"
    gpu = probe_gpu()
    if requested == "cuda":
        if not gpu.torch_cuda_available:
            raise RuntimeError("CUDA requested but unavailable")
        return "cuda:0"
    # auto
    return "cuda:0" if gpu.torch_cuda_available else "cpu"
