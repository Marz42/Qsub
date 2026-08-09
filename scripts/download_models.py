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
import uuid
from pathlib import Path

from qsub_core.model_store import load_model_lock, validate_model_dir, write_model_marker


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
    root = resolve_install_root()
    if (root / "pyproject.toml").is_file() and (root / "src" / "qsub_core").is_dir():
        return root / "models"
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "QwenSubtitle" / "models"
    return Path.home() / ".qwensubtitle" / "models"


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


def _targets(models: Path, lock: dict) -> dict[str, dict]:
    by_name = {str(e.get("name")): e for e in lock.get("entries") or []}
    return {
        "asr": {
            "repo": "Qwen/Qwen3-ASR-0.6B",
            "dest": models / "Qwen3-ASR-0.6B",
            "entry": by_name["Qwen3-ASR-0.6B"],
        },
        "aligner": {
            "repo": "Qwen/Qwen3-ForcedAligner-0.6B",
            "dest": models / "Qwen3-ForcedAligner-0.6B",
            "entry": by_name["Qwen3-ForcedAligner-0.6B"],
        },
        "vad": {
            "repo": "snakers4/silero-vad",
            "dest": models / "silero-vad",
            "entry": by_name["silero-vad"],
            "note": "Exports silero_vad.jit from the installed silero-vad package (offline).",
        },
    }


def _required_bytes(entry: dict) -> int:
    return sum(int(item.get("size") or 0) for item in entry.get("required_files") or [])


def _commit_staging(staging: Path, dest: Path) -> None:
    backup = dest.with_name(f"{dest.name}.backup-{uuid.uuid4().hex[:8]}")
    moved_old = False
    committed = False
    try:
        if dest.exists():
            dest.replace(backup)
            moved_old = True
        staging.replace(dest)
        committed = True
    except Exception:
        if moved_old and backup.exists() and not dest.exists():
            backup.replace(dest)
        raise
    finally:
        if committed and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


def _install_target(key: str, target: dict) -> None:
    dest: Path = target["dest"]
    entry: dict = target["entry"]
    current = validate_model_dir(dest, entry, verify_hashes=True)
    if current["ok"]:
        if not current["revision_verified"]:
            write_model_marker(dest, entry)
        print(f"Already verified: {dest}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    required = _required_bytes(entry)
    free = shutil.disk_usage(dest.parent).free
    if required and free < required + 512 * 1024 * 1024:
        raise RuntimeError(
            f"insufficient disk space for {entry.get('name')}: "
            f"need at least {(required + 512 * 1024 * 1024) / (1024**3):.2f} GiB"
        )

    staging = dest.with_name(f"{dest.name}.staging-{uuid.uuid4().hex[:8]}")
    try:
        if key == "vad":
            export_silero_vad(staging)
        else:
            try:
                from huggingface_hub import snapshot_download
            except ImportError as exc:
                raise RuntimeError(
                    "缺少 huggingface_hub。便携/安装包请使用带 fetch extra 的 runtime；"
                    "开发树：uv sync --extra fetch 或 --extra dev"
                ) from exc
            revision = str(entry.get("revision") or "")
            if not revision:
                raise RuntimeError(f"model revision is not pinned: {entry.get('name')}")
            print(f"Downloading {target['repo']}@{revision} -> {staging} ...")
            snapshot_download(
                repo_id=target["repo"],
                revision=revision,
                local_dir=str(staging),
            )
        checked = validate_model_dir(staging, entry, verify_hashes=True)
        if not checked["ok"]:
            raise RuntimeError(
                f"model verification failed for {entry.get('name')}: "
                + "; ".join(checked["issues"])
            )
        write_model_marker(staging, entry)
        _commit_staging(staging, dest)
        print(f"Installed and verified: {dest}")
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


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
    lock_path = root / "manifests" / "model-lock.json"
    lock = load_model_lock(lock_path)
    targets = _targets(models, lock)
    keys = ["asr", "aligner", "vad"] if args.only == "all" else [args.only]

    print(f"Install root: {root}")
    print(f"Models dir:   {models}")
    for key in keys:
        t = targets[key]
        print(f"[{key}] repo={t['repo']} revision={t['entry'].get('revision')}")
        print(f"      dest={t['dest']}")
        if t.get("note"):
            print(f"      note={t['note']}")

    if not args.confirm_download:
        print("\n仅预览。确认后请执行：")
        print(f"  {Path(sys.executable).name} {Path(__file__).name} --confirm-download")
        print("或在安装目录运行：download-models.cmd")
        return 0

    try:
        for key in keys:
            _install_target(key, targets[key])
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"下载/验证失败：{exc}", file=sys.stderr)
        return 3

    print("完成。可运行：qsub doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
