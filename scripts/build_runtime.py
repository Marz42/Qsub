#!/usr/bin/env python3
"""
Assemble a portable Windows layout (Phase 6 — Runtime Packaging).

Output:
  dist/portable/QwenSubtitle/
    qsub.cmd / download-models.cmd
    qsub.ps1
    launcher/
    runtime/          # relocatable uv venv (gui + fetch extras)
    bin/              # ffmpeg/ffprobe (optional --with-ffmpeg)
    models/           # VAD export by default; ASR/Aligner via download-models.cmd
    scripts/download_models.py
    manifests/
    README.txt

Default releases omit ASR/Aligner weights. After download-models.cmd once,
a clean machine (no system Python / CUDA Toolkit / FFmpeg on PATH) can run
offline with the bundled runtime.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "dist" / "portable" / "QwenSubtitle"


def run(cmd: list[str], *, env: dict | None = None, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, env=env, cwd=str(cwd or ROOT))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\r\n" if path.suffix.lower() in {".cmd", ".bat", ".ps1", ".txt"} else "\n")


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> int:
    p = argparse.ArgumentParser(description="Build portable QwenSubtitle runtime layout")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--python", default="3.12", help="Python version for uv venv")
    p.add_argument("--with-ffmpeg", action="store_true", help="Download pinned FFmpeg into bin/")
    p.add_argument(
        "--with-models",
        action="store_true",
        help="Optional: copy ASR/Aligner from repo models/ (air-gap OEM; not default release)",
    )
    p.add_argument("--clean", action="store_true", help="Remove existing --out first")
    args = p.parse_args()

    out: Path = args.out.resolve()
    if args.clean and out.exists():
        print(f"Removing {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    runtime = out / "runtime"
    manifests = out / "manifests"
    bin_dir = out / "bin"
    models = out / "models"
    launcher_dir = out / "launcher"

    # 1) Relocatable venv
    if runtime.exists():
        shutil.rmtree(runtime)
    venv_cmd = ["uv", "venv", str(runtime), "--python", args.python, "--relocatable"]
    try:
        run(venv_cmd)
    except subprocess.CalledProcessError:
        # Older uv without --relocatable
        run(["uv", "venv", str(runtime), "--python", args.python])

    python_exe = runtime / "Scripts" / "python.exe"
    if not python_exe.is_file():
        print(f"missing {python_exe}")
        return 1

    # 2) Install locked project + deps + GUI + fetch (huggingface_hub) into the venv
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(runtime)
    run(
        ["uv", "sync", "--frozen", "--no-dev", "--extra", "gui", "--extra", "fetch"],
        env=env,
    )

    # Ensure console script / GUI import path exist
    run(
        [
            str(python_exe),
            "-c",
            "import qsub_core, torch, gui; print(qsub_core.__version__, torch.__version__, gui.__version__)",
        ]
    )

    # 3) Manifests / launcher / scripts
    manifests.mkdir(parents=True, exist_ok=True)
    for name in ("runtime-lock.json", "model-lock.json", "ffmpeg-lock.json", "licenses.json"):
        src = ROOT / "manifests" / name
        if src.is_file():
            shutil.copy2(src, manifests / name)

    # Refresh runtime-lock versions from the portable env
    try:
        versions = subprocess.check_output(
            [
                str(python_exe),
                "-c",
                "import importlib.metadata as m, json, sys; "
                "pkgs=['torch','qwen-asr','transformers','numpy','silero-vad','torchaudio']; "
                "print(json.dumps({p:(m.version(p) if True else None) for p in pkgs}))",
            ],
            text=True,
            errors="replace",
        )
        ver = json.loads(versions)
        lock_path = manifests / "runtime-lock.json"
        if lock_path.is_file():
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            by_name = {e["name"]: e for e in lock.get("entries") or []}
            for name, version in ver.items():
                if name in by_name:
                    by_name[name]["version"] = version
            lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"warning: could not refresh runtime-lock versions: {exc}")

    launcher_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "launcher" / "qsub_launcher.py", launcher_dir / "qsub_launcher.py")
    shutil.copy2(ROOT / "launcher" / "gui_launcher.py", launcher_dir / "gui_launcher.py")

    write_text(
        out / "qsub.cmd",
        "@echo off\r\n"
        "setlocal\r\n"
        "set \"QSUB_ROOT=%~dp0\"\r\n"
        "\"%~dp0runtime\\Scripts\\python.exe\" -m qsub_core.cli %*\r\n"
        "exit /b %ERRORLEVEL%\r\n",
    )
    write_text(
        out / "qsub.ps1",
        "$ErrorActionPreference = 'Stop'\r\n"
        "$root = Split-Path -Parent $MyInvocation.MyCommand.Path\r\n"
        "$env:QSUB_ROOT = $root\r\n"
        "& \"$root\\runtime\\Scripts\\python.exe\" -m qsub_core.cli @args\r\n"
        "exit $LASTEXITCODE\r\n",
    )
    # GUI: prefer pythonw (no console). Spec name QwenSubtitle.exe ≈ this entry + Start Menu shortcut.
    write_text(
        out / "QwenSubtitle.cmd",
        "@echo off\r\n"
        "setlocal\r\n"
        "set \"QSUB_ROOT=%~dp0\"\r\n"
        "if exist \"%~dp0runtime\\Scripts\\pythonw.exe\" (\r\n"
        "  start \"\" \"%~dp0runtime\\Scripts\\pythonw.exe\" -m gui.main %*\r\n"
        ") else (\r\n"
        "  start \"\" \"%~dp0runtime\\Scripts\\python.exe\" -m gui.main %*\r\n"
        ")\r\n",
    )
    write_text(
        out / "QwenSubtitle.vbs",
        'Set sh = CreateObject("WScript.Shell")\r\n'
        'Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
        'root = fso.GetParentFolderName(WScript.ScriptFullName)\r\n'
        'sh.Environment("PROCESS")("QSUB_ROOT") = root\r\n'
        'pyw = root & "\\runtime\\Scripts\\pythonw.exe"\r\n'
        'If Not fso.FileExists(pyw) Then pyw = root & "\\runtime\\Scripts\\python.exe"\r\n'
        'sh.Run """" & pyw & """ -m gui.main", 0, False\r\n',
    )

    # 4) FFmpeg
    bin_dir.mkdir(parents=True, exist_ok=True)
    write_text(bin_dir / "README.md", "# Place ffmpeg.exe and ffprobe.exe here.\n")
    if args.with_ffmpeg:
        run([sys.executable, str(ROOT / "scripts" / "fetch_ffmpeg.py"), "--dest-bin", str(bin_dir)])

    # 5) Models — default: no ASR/Aligner weights (user runs download-models.cmd).
    # Always export tiny VAD jit from the portable env's silero-vad package.
    models.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "models" / "README.md", models / "README.md")
    scripts_out = out / "scripts"
    scripts_out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "scripts" / "download_models.py", scripts_out / "download_models.py")
    write_text(
        out / "download-models.cmd",
        "@echo off\r\n"
        "setlocal\r\n"
        "set \"QSUB_ROOT=%~dp0\"\r\n"
        "echo Downloading ASR/Aligner (and exporting VAD) into %%QSUB_ROOT%%models\r\n"
        "echo Requires network for Hugging Face weights. Ctrl+C to cancel.\r\n"
        "\"%~dp0runtime\\Scripts\\python.exe\" \"%~dp0scripts\\download_models.py\" --confirm-download %*\r\n"
        "exit /b %ERRORLEVEL%\r\n",
    )
    print("Exporting silero-vad into models/silero-vad …")
    vad_export = subprocess.run(
        [
            str(python_exe),
            str(scripts_out / "download_models.py"),
            "--only",
            "vad",
            "--confirm-download",
            "--models-dir",
            str(models),
        ],
        cwd=str(out),
    )
    if vad_export.returncode != 0:
        print("warning: VAD export failed; user can re-run download-models.cmd --only vad")

    if args.with_models:
        print("NOTE: --with-models is optional (air-gap OEM). Default releases omit ASR/Aligner.")
        for name in ("Qwen3-ASR-0.6B", "Qwen3-ForcedAligner-0.6B", "silero-vad"):
            src = ROOT / "models" / name
            if src.is_dir() and any(src.iterdir()):
                print(f"Copying models/{name} …")
                copy_tree(src, models / name)
            else:
                print(f"warning: models/{name} missing; skip")

    # 5b) License notices for installer / portable tree
    licenses_dir = out / "licenses"
    licenses_dir.mkdir(parents=True, exist_ok=True)
    src_lic = ROOT / "licenses"
    if src_lic.is_dir():
        for f in src_lic.iterdir():
            if f.is_file():
                shutil.copy2(f, licenses_dir / f.name)
    ofl = ROOT / "gui" / "fonts" / "NotoSansSC" / "OFL.txt"
    if ofl.is_file():
        shutil.copy2(ofl, licenses_dir / "NotoSansSC-OFL.txt")

    # 5c) Bundle GUI fonts next to install root (also shipped via wheel force-include)
    fonts_src = ROOT / "gui" / "fonts"
    if fonts_src.is_dir():
        copy_tree(fonts_src, out / "gui" / "fonts")

    write_text(
        out / "README.txt",
        "QwenSubtitle portable runtime (CLI + Chinese GUI)\r\n"
        "\r\n"
        "GUI:\r\n"
        "  QwenSubtitle.vbs   (recommended, no console)\r\n"
        "  QwenSubtitle.cmd\r\n"
        "\r\n"
        "CLI:\r\n"
        "  qsub.cmd doctor\r\n"
        "  qsub.cmd probe video.mp4\r\n"
        "  qsub.cmd transcribe video.mp4 --language Chinese --overwrite\r\n"
        "\r\n"
        "Models (NOT bundled by default):\r\n"
        "  1. Connect to the internet once\r\n"
        "  2. Run download-models.cmd  (writes ASR/Aligner under models\\)\r\n"
        "  3. qsub.cmd doctor  -> READY\r\n"
        "  Afterwards the app works offline. Transcription never auto-downloads.\r\n"
        "\r\n"
        "Requirements:\r\n"
        "  - NVIDIA driver (CUDA Toolkit NOT required)\r\n"
        "  - Models under models\\ (or set QSUB_MODELS_DIR)\r\n"
        "  - ffmpeg/ffprobe under bin\\ (or on PATH)\r\n"
        "\r\n"
        "This tree embeds its own Python runtime under runtime\\.\r\n"
        "See licenses\\ for third-party notices.\r\n",
    )

    # 6) Smoke
    print("Smoke: qsub.cmd doctor")
    smoke = subprocess.run([str(out / "qsub.cmd"), "doctor"], cwd=str(out))
    if smoke.returncode not in (0, 1):
        # doctor returns 1 when NOT_READY (e.g. models missing in portable without --with-models)
        print(f"doctor exited {smoke.returncode}")
        return smoke.returncode

    print(f"Portable layout ready: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
