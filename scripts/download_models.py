#!/usr/bin/env python3
"""
Explicit model fetch helper.

Never called implicitly by transcribe. User (or release engineer) must pass
--confirm-download. Works in the git checkout and in a portable/install tree
(scripts/download_models.py next to models/).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def resolve_install_root() -> Path:
    """Repo root or portable/install root containing models/."""
    env = os.environ.get("QSUB_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    # <root>/scripts/download_models.py
    if here.parent.name == "scripts":
        return here.parent.parent
    return here.parent


def resolve_models_dir(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    env = os.environ.get("QSUB_MODELS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return resolve_install_root() / "models"


def export_silero_vad(dest: Path) -> None:
    """Copy weight files from site-packages without importing silero_vad (avoids torchaudio)."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        from importlib.metadata import distribution
    except ImportError as exc:
        raise SystemExit("importlib.metadata unavailable") from exc

    try:
        dist = distribution("silero-vad")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "silero-vad not installed. Install the app runtime (or: uv sync) and re-run."
        ) from exc

    copied = 0
    for file in dist.files or []:
        name = Path(file.name).name
        if name in {"silero_vad.jit", "silero_vad.onnx", "silero_vad_16k_op15.onnx"} or (
            name.startswith("silero_vad") and name.endswith((".jit", ".onnx"))
        ):
            src = Path(dist.locate_file(file))
            if src.is_file():
                shutil.copy2(src, dest / name)
                print(f"Copied {name} -> {dest / name}")
                copied += 1
    if copied == 0:
        raise SystemExit("could not locate bundled silero_vad weights in package files")


def _targets(models: Path) -> dict[str, dict]:
    return {
        "asr": {
            "repo": "Qwen/Qwen3-ASR-0.6B",
            "dest": models / "Qwen3-ASR-0.6B",
        },
        "aligner": {
            "repo": "Qwen/Qwen3-ForcedAligner-0.6B",
            "dest": models / "Qwen3-ForcedAligner-0.6B",
        },
        "vad": {
            "repo": "snakers4/silero-vad",
            "dest": models / "silero-vad",
            "note": "Exports silero_vad.jit from the installed silero-vad package (offline).",
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="显式下载/导出本地模型（转录不会自动调用本脚本）"
    )
    p.add_argument(
        "--confirm-download",
        action="store_true",
        help="实际执行下载/导出（默认仅打印计划）",
    )
    p.add_argument("--only", choices=["asr", "aligner", "vad", "all"], default="all")
    p.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="模型目录（默认：QSUB_MODELS_DIR 或 <安装根>/models）",
    )
    args = p.parse_args()

    models = resolve_models_dir(args.models_dir)
    root = resolve_install_root()
    targets = _targets(models)
    keys = ["asr", "aligner", "vad"] if args.only == "all" else [args.only]

    print(f"Install root: {root}")
    print(f"Models dir:   {models}")
    for key in keys:
        t = targets[key]
        print(f"[{key}] repo={t['repo']}")
        print(f"      dest={t['dest']}")
        if t.get("note"):
            print(f"      note={t['note']}")

    if not args.confirm_download:
        print("\n仅预览。确认后请执行：")
        print(f"  {Path(sys.executable).name} {Path(__file__).name} --confirm-download")
        print("或在安装目录运行：download-models.cmd")
        return 0

    for key in keys:
        t = targets[key]
        if key == "vad":
            export_silero_vad(t["dest"])
            continue
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            print(
                "缺少 huggingface_hub。便携/安装包请用带 fetch extra 的 runtime；"
                "开发树：uv sync --extra fetch 或 --extra dev",
                file=sys.stderr,
            )
            return 2
        t["dest"].parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {t['repo']} -> {t['dest']} ...")
        snapshot_download(repo_id=t["repo"], local_dir=str(t["dest"]))
        print(f"Done: {t['dest']}")

    print("完成。可运行：qsub doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
