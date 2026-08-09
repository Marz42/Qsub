#!/usr/bin/env python3
"""
Assemble a portable Windows layout (Phase 6 — Runtime Packaging).

Output:
  dist/portable/QwenSubtitle/
    qsub.cmd / download-models.cmd
    qsub.ps1
    launcher/
    runtime/          # complete standalone CPython + locked site-packages
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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _standalone_python_issue(exe: Path) -> str | None:
    root = exe.parent
    if root.name.lower() == "scripts" or (root / "pyvenv.cfg").is_file():
        return "is a virtual-environment interpreter"
    if not exe.is_file() or not (root / "Lib").is_dir() or not list(root.glob("python3*.dll")):
        return "is not a complete standalone CPython tree"
    return None


def _python_version(exe: Path, *, env: dict[str, str]) -> str:
    return subprocess.check_output(
        [str(exe), "-I", "-c", "import platform; print(platform.python_version())"],
        cwd=str(exe.parent),
        env=env,
        text=True,
        errors="replace",
    ).strip()


def _version_key(version: str) -> tuple[int, ...]:
    match = re.fullmatch(r"\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?\s*", version)
    if not match:
        return ()
    return tuple(int(part) for part in match.groups() if part is not None)


def _version_matches(spec: str, version: str) -> bool:
    requested = _version_key(spec)
    actual = _version_key(version)
    return bool(requested) and actual[: len(requested)] == requested


def _managed_python_candidates(managed_dir: Path) -> list[Path]:
    """Return only bounded candidates within uv's managed installation directory."""
    candidates = [managed_dir / "python.exe", managed_dir / "install" / "python.exe"]
    if managed_dir.is_dir():
        for child in managed_dir.iterdir():
            if child.is_dir():
                candidates.extend((child / "python.exe", child / "install" / "python.exe"))
    return list(dict.fromkeys(candidate.resolve() for candidate in candidates))


def find_standalone_python(spec: str) -> Path:
    """Resolve a complete uv-managed CPython installation, never a project venv."""
    clean_env = os.environ.copy()
    for name in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "CONDA_PREFIX", "PYTHONHOME", "PYTHONPATH"):
        clean_env.pop(name, None)

    # An explicit executable/root remains useful for controlled build agents.
    requested_path = Path(spec).expanduser()
    explicit = requested_path / "python.exe" if requested_path.is_dir() else requested_path
    if explicit.is_file():
        explicit = explicit.resolve()
        issue = _standalone_python_issue(explicit)
        if issue:
            raise RuntimeError(f"Requested Python {explicit} {issue}")
        return explicit

    errors: list[str] = []
    managed_dir: Path | None = None
    try:
        raw = subprocess.check_output(
            ["uv", "python", "dir"],
            cwd=str(ROOT),
            env=clean_env,
            text=True,
            errors="replace",
        ).strip()
        managed_dir = Path(raw).expanduser().resolve()
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"uv python dir: {exc}")

    matches: list[tuple[tuple[int, ...], Path]] = []
    if managed_dir is not None:
        for exe in _managed_python_candidates(managed_dir):
            issue = _standalone_python_issue(exe)
            if issue:
                continue
            try:
                version = _python_version(exe, env=clean_env)
            except (OSError, subprocess.CalledProcessError) as exc:
                errors.append(f"{exe} could not report its version: {exc}")
                continue
            if _version_matches(spec, version):
                matches.append((_version_key(version), exe))

    if matches:
        # Prefer the newest installed patch release for a major/minor request.
        return max(matches, key=lambda item: item[0])[1]

    location = f" under {managed_dir}" if managed_dir is not None else ""
    detail = f" Details: {'; '.join(errors)}" if errors else ""
    raise RuntimeError(
        f"Could not locate a complete uv-managed CPython {spec}{location}. "
        f"Run `uv python install {spec}` first.{detail}"
    )


def install_locked_site_packages(runtime: Path, python: Path, out_parent: Path) -> None:
    """Resolve with uv in a staging venv, then copy a non-editable install."""
    staging = Path(tempfile.mkdtemp(prefix="qsub-build-venv-", dir=str(out_parent)))
    try:
        run(["uv", "venv", str(staging), "--python", str(python)])
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env["UV_PROJECT_ENVIRONMENT"] = str(staging)
        run(
            [
                "uv",
                "sync",
                "--frozen",
                "--no-editable",
                "--no-dev",
                "--extra",
                "gui",
                "--extra",
                "fetch",
            ],
            env=env,
        )
        source_packages = staging / "Lib" / "site-packages"
        if not source_packages.is_dir():
            raise RuntimeError(f"staging site-packages missing: {source_packages}")
        shutil.copytree(
            source_packages,
            runtime / "Lib" / "site-packages",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def assert_runtime_is_self_contained(runtime: Path, python_exe: Path) -> None:
    """Reject venv metadata, editable installs, and external absolute .pth entries."""
    if (runtime / "pyvenv.cfg").exists():
        raise RuntimeError("standalone runtime unexpectedly contains pyvenv.cfg")
    site_packages = runtime / "Lib" / "site-packages"
    for editable in site_packages.glob("*editable*.pth"):
        raise RuntimeError(f"editable install leaked into release runtime: {editable}")
    runtime_resolved = runtime.resolve()
    for pth in site_packages.glob("*.pth"):
        for raw in pth.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "import ")):
                continue
            candidate = Path(line)
            if candidate.is_absolute():
                try:
                    candidate.resolve().relative_to(runtime_resolved)
                except ValueError as exc:
                    raise RuntimeError(f"external absolute path in {pth}: {line}") from exc
    run(
        [
            str(python_exe),
            "-I",
            "-c",
            "import pathlib,sys,qsub_core,torch,gui; "
            "root=pathlib.Path(sys.base_prefix).resolve(); expected=pathlib.Path(sys.argv[1]).resolve(); "
            "assert root==expected,(root,expected); "
            "print(qsub_core.__version__, torch.__version__, gui.__version__, root)",
            str(runtime),
        ],
        cwd=runtime,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Build portable QwenSubtitle runtime layout")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--python", default="3.12", help="uv-managed standalone Python version")
    p.add_argument("--with-ffmpeg", action="store_true", help="Download pinned FFmpeg into bin/")
    p.add_argument(
        "--with-models",
        action="store_true",
        help="Optional: copy ASR/Aligner from repo models/ (air-gap OEM; not default release)",
    )
    p.add_argument("--clean", action="store_true", help="Remove existing --out first")
    args = p.parse_args()

    # Resolve prerequisites before --clean removes a previously usable build.
    managed_python = find_standalone_python(args.python)
    if args.with_models:
        run([sys.executable, str(ROOT / "scripts" / "verify_models.py")])

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

    # 1) Complete standalone CPython + locked, non-editable site-packages.
    # A relocatable venv is still dependent on its base interpreter and is not
    # a distributable runtime on Windows.
    if runtime.exists():
        shutil.rmtree(runtime)
    print(f"Copying standalone CPython from {managed_python.parent}")
    shutil.copytree(
        managed_python.parent,
        runtime,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    python_exe = runtime / "python.exe"
    if not python_exe.is_file():
        print(f"missing {python_exe}")
        return 1
    install_locked_site_packages(runtime, managed_python, out.parent)
    assert_runtime_is_self_contained(runtime, python_exe)

    # 3) Manifests / launcher / scripts
    manifests.mkdir(parents=True, exist_ok=True)
    for name in ("runtime-lock.json", "model-lock.json", "ffmpeg-lock.json", "licenses.json"):
        src = ROOT / "manifests" / name
        if src.is_file():
            shutil.copy2(src, manifests / name)

    # Refresh runtime-lock from the actual portable interpreter and bind it to uv.lock.
    try:
        versions = subprocess.check_output(
            [
                str(python_exe),
                "-c",
                "import importlib.metadata as m, json, platform, sys; "
                "pkgs=['torch','qwen-asr','transformers','numpy','silero-vad','torchaudio']; "
                "print(json.dumps({'python':platform.python_version(),'packages':{p:m.version(p) for p in pkgs}}))",
            ],
            text=True,
            errors="replace",
        )
        actual = json.loads(versions)
        ver = actual["packages"]
        lock_path = manifests / "runtime-lock.json"
        if lock_path.is_file():
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            by_name = {e["name"]: e for e in lock.get("entries") or []}
            if "python" in by_name:
                by_name["python"]["version"] = actual["python"]
                by_name["python"]["sha256"] = sha256_file(python_exe)
            for name, version in ver.items():
                if name in by_name:
                    by_name[name]["version"] = version
            uv_lock = ROOT / "uv.lock"
            lock["integrity"] = {
                "dependency_lock": "uv.lock",
                "uv_lock_sha256": sha256_file(uv_lock),
            }
            lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
            shutil.copy2(uv_lock, manifests / "uv.lock")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"could not create verified runtime manifest: {exc}") from exc

    launcher_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "launcher" / "qsub_launcher.py", launcher_dir / "qsub_launcher.py")
    shutil.copy2(ROOT / "launcher" / "gui_launcher.py", launcher_dir / "gui_launcher.py")

    write_text(
        out / "qsub.cmd",
        "@echo off\r\n"
        "setlocal\r\n"
        "set \"QSUB_ROOT=%~dp0\"\r\n"
        "\"%~dp0runtime\\python.exe\" -I -m qsub_core.cli %*\r\n"
        "exit /b %ERRORLEVEL%\r\n",
    )
    write_text(
        out / "qsub.ps1",
        "$ErrorActionPreference = 'Stop'\r\n"
        "$root = Split-Path -Parent $MyInvocation.MyCommand.Path\r\n"
        "$env:QSUB_ROOT = $root\r\n"
        "& \"$root\\runtime\\python.exe\" -I -m qsub_core.cli @args\r\n"
        "exit $LASTEXITCODE\r\n",
    )
    # GUI: prefer pythonw (no console). Spec name QwenSubtitle.exe ≈ this entry + Start Menu shortcut.
    write_text(
        out / "QwenSubtitle.cmd",
        "@echo off\r\n"
        "setlocal\r\n"
        "set \"QSUB_ROOT=%~dp0\"\r\n"
        "if exist \"%~dp0runtime\\pythonw.exe\" (\r\n"
        "  start \"\" \"%~dp0runtime\\pythonw.exe\" -I -m gui.main %*\r\n"
        ") else (\r\n"
        "  start \"\" \"%~dp0runtime\\python.exe\" -I -m gui.main %*\r\n"
        ")\r\n",
    )
    write_text(
        out / "QwenSubtitle.vbs",
        'Set sh = CreateObject("WScript.Shell")\r\n'
        'Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
        'root = fso.GetParentFolderName(WScript.ScriptFullName)\r\n'
        'sh.Environment("PROCESS")("QSUB_ROOT") = root\r\n'
        'pyw = root & "\\runtime\\pythonw.exe"\r\n'
        'If Not fso.FileExists(pyw) Then pyw = root & "\\runtime\\python.exe"\r\n'
        # pythonw.exe has no console to hide. Window style 0 would also hide
        # the Qt main window, leaving a live process with no visible UI.
        'sh.Run """" & pyw & """ -I -m gui.main", 1, False\r\n',
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
        "echo Downloading pinned ASR/Aligner into %%LOCALAPPDATA%%\\QwenSubtitle\\models\r\n"
        "echo Requires network for Hugging Face weights. Ctrl+C to cancel.\r\n"
        "\"%~dp0runtime\\python.exe\" -I \"%~dp0scripts\\download_models.py\" --confirm-download %*\r\n"
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
        copied_all = True
        for name in ("Qwen3-ASR-0.6B", "Qwen3-ForcedAligner-0.6B", "silero-vad"):
            src = ROOT / "models" / name
            if src.is_dir() and any(src.iterdir()):
                print(f"Copying models/{name} …")
                copy_tree(src, models / name)
            else:
                print(f"warning: models/{name} missing; skip")
                copied_all = False
        if copied_all:
            write_text(
                models / ".qsub-bundled-models.json",
                json.dumps({"schema_version": 1, "source": "verified release build"}, indent=2) + "\n",
            )

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

    # 5c) Bundle GUI fonts next to install root (also shipped as wheel package data).
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
        "Models (NOT bundled by default; pinned and verified):\r\n"
        "  1. Connect to the internet once\r\n"
        "  2. Run download-models.cmd  (writes under %LOCALAPPDATA%\\QwenSubtitle\\models)\r\n"
        "  3. qsub.cmd doctor  -> READY\r\n"
        "  Afterwards the app works offline. Transcription never auto-downloads.\r\n"
        "\r\n"
        "Requirements:\r\n"
        "  - NVIDIA driver (CUDA Toolkit NOT required)\r\n"
        "  - Models under %%LOCALAPPDATA%%\\QwenSubtitle\\models (or set QSUB_MODELS_DIR)\r\n"
        "  - ffmpeg/ffprobe under bin\\ (or on PATH)\r\n"
        "\r\n"
        "This tree embeds a complete standalone Python runtime under runtime\\.\r\n"
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
