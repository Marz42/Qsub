"""qsub doctor — installation / runtime diagnostics (Spec §52)."""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from qsub_core import __version__
from qsub_core.config import (
    aligner_model_path,
    asr_model_path,
    ensure_user_dirs,
    vad_model_path,
)
from qsub_core.model_store import model_entry, validate_model_dir
from qsub_core.system.binaries import find_executable
from qsub_core.system.gpu import probe_gpu


def _model_status(path: Path, name: str) -> dict[str, Any]:
    try:
        return validate_model_dir(path, model_entry(name), verify_hashes=False)
    except (OSError, ValueError, KeyError) as exc:
        return {"path": str(path), "ok": False, "issues": [str(exc)]}


def _vad_status() -> dict[str, Any]:
    path = vad_model_path()
    from qsub_core.vad.silero import _find_local_model_file

    local = _find_local_model_file(path)
    if local is not None:
        return {"path": str(path), "ok": True, "source": str(local)}
    try:
        import silero_vad  # noqa: F401

        return {"path": str(path), "ok": True, "source": "silero-vad-package"}
    except ImportError:
        return {"path": str(path), "ok": False, "source": None}


def collect_doctor_report() -> dict[str, Any]:
    gpu = probe_gpu()
    user_dirs = ensure_user_dirs()
    writable = os.access(user_dirs["root"], os.W_OK)

    ffmpeg = find_executable("ffmpeg")
    ffprobe = find_executable("ffprobe")

    asr = _model_status(asr_model_path(), "Qwen3-ASR-0.6B")
    aligner = _model_status(aligner_model_path(), "Qwen3-ForcedAligner-0.6B")
    vad = _vad_status()

    checks = {
        "windows": platform.system() == "Windows",
        "arch_x64": platform.machine().lower() in {"amd64", "x86_64"},
        "ffmpeg": ffmpeg is not None,
        "ffprobe": ffprobe is not None,
        "torch_cuda": gpu.torch_cuda_available,
        "asr_model": asr["ok"],
        "aligner_model": aligner["ok"],
        "vad_model": vad["ok"],
        "user_data_writable": writable,
    }
    ready = all(
        [
            checks["windows"],
            checks["arch_x64"],
            checks["ffmpeg"],
            checks["ffprobe"],
            checks["asr_model"],
            checks["aligner_model"],
            checks["vad_model"],
            checks["user_data_writable"],
        ]
    )

    return {
        "app": f"QwenSubtitle {__version__}",
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "ram": _ram_info(),
        "gpu": gpu.to_dict(),
        "ffmpeg": str(ffmpeg) if ffmpeg else None,
        "ffprobe": str(ffprobe) if ffprobe else None,
        "models": {"asr": asr, "aligner": aligner, "vad": vad},
        "user_data": {k: str(v) for k, v in user_dirs.items()},
        "checks": checks,
        "status": "READY" if ready else "NOT_READY",
        "ready": ready,
    }


def format_doctor_text(report: dict[str, Any]) -> str:
    gpu = report.get("gpu") or {}
    vram = gpu.get("vram_gb")
    vram_s = f"{vram} GB" if vram is not None else "n/a"
    checks = report["checks"]
    lines = [
        report["app"],
        "",
        f"Windows:      {'OK' if checks['windows'] else 'FAIL'}",
        f"Arch:         {report['platform']['machine']}",
        f"GPU:          {gpu.get('name') or 'n/a'}",
        f"VRAM:         {vram_s}",
        f"PyTorch CUDA: {'OK' if checks['torch_cuda'] else 'NO'}",
        f"FFmpeg:       {'OK' if checks['ffmpeg'] else 'MISSING'}",
        f"FFprobe:      {'OK' if checks['ffprobe'] else 'MISSING'}",
        f"ASR Model:    {'OK' if checks['asr_model'] else 'MISSING'}",
        f"Aligner:      {'OK' if checks['aligner_model'] else 'MISSING'}",
        f"VAD:          {'OK' if checks.get('vad_model') else 'MISSING'}",
        f"User data:    {'OK' if checks['user_data_writable'] else 'FAIL'}",
        "",
        f"Status: {report['status']}",
    ]
    if not (checks["asr_model"] and checks["aligner_model"]):
        lines.extend(
            [
                "",
                "Models are not bundled with the installer by default.",
                "Run once from the install/portable root (needs network):",
                "  download-models.cmd",
                "Models are stored under %LOCALAPPDATA%\\QwenSubtitle\\models.",
                "Or (dev tree):",
                "  uv run python scripts/download_models.py --confirm-download",
                "Then re-run: qsub doctor",
            ]
        )
    return "\n".join(lines)


def run_doctor(*, as_json: bool = False) -> int:
    report = collect_doctor_report()
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_doctor_text(report))
    return 0 if report["ready"] else 1


def _ram_info() -> dict[str, Any]:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return {
                "total_bytes": int(stat.ullTotalPhys),
                "available_bytes": int(stat.ullAvailPhys),
                "total_gb": round(stat.ullTotalPhys / (1024**3), 2),
            }
    except Exception:  # noqa: BLE001
        pass
    return {"total_bytes": None, "available_bytes": None, "total_gb": None}
