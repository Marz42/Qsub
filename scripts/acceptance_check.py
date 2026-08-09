#!/usr/bin/env python3
"""
Phase 9 acceptance gate (Spec §54–§55).

Automated checks for the current machine/release tree. Hardware matrix rows
(RTX 30, Win10, 60 min, …) remain manual — see acceptance/README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def check_pytest() -> tuple[bool, str]:
    proc = _run([sys.executable, "-m", "pytest", "-q", "--tb=line"])
    ok = proc.returncode == 0
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    detail = " | ".join(tail) if tail else f"exit {proc.returncode}"
    if not ok and proc.stderr:
        detail += " " + proc.stderr.strip().splitlines()[-1]
    return ok, detail


def check_doctor() -> tuple[bool, str]:
    env = os.environ.copy()
    # Prefer repo models over a stale portable QSUB_ROOT without weights
    env.pop("QSUB_ROOT", None)
    proc = _run([sys.executable, "-m", "qsub_core.cli", "doctor", "--json"], env=env)
    if proc.returncode not in (0, 1):
        return False, f"doctor exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return False, f"invalid doctor JSON: {exc}"
    ready = bool(report.get("ready"))
    gpu = (report.get("gpu") or {}).get("name") or "n/a"
    status = report.get("status")
    return ready, f"{status}; GPU={gpu}; cuda={report.get('checks', {}).get('torch_cuda')}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_locks(root: Path = ROOT) -> tuple[bool, str]:
    required = [
        root / "manifests" / "runtime-lock.json",
        root / "manifests" / "model-lock.json",
        root / "manifests" / "ffmpeg-lock.json",
        root / "manifests" / "licenses.json",
    ]
    uv_lock = root / "uv.lock"
    if not uv_lock.is_file():
        uv_lock = root / "manifests" / "uv.lock"
    required.append(uv_lock)
    missing = [str(p.relative_to(root)) for p in required if not p.is_file()]
    if missing:
        return False, "missing: " + ", ".join(missing)
    try:
        model_lock = json.loads((root / "manifests" / "model-lock.json").read_text(encoding="utf-8"))
        for entry in model_lock.get("entries") or []:
            revision = str(entry.get("revision") or "")
            if not revision or "TBD" in revision:
                return False, f"model revision not pinned: {entry.get('name')}"
            files = entry.get("required_files") or []
            if not files:
                return False, f"model file manifest missing: {entry.get('name')}"
            for item in files:
                digest = str(item.get("sha256") or "")
                if len(digest) != 64 or not item.get("size"):
                    return False, f"invalid model file lock: {entry.get('name')}/{item.get('path')}"
        ffmpeg_lock = json.loads((root / "manifests" / "ffmpeg-lock.json").read_text(encoding="utf-8"))
        if any(len(str(e.get("sha256") or "")) != 64 for e in ffmpeg_lock.get("entries") or []):
            return False, "FFmpeg hashes are incomplete"
        runtime_lock = json.loads((root / "manifests" / "runtime-lock.json").read_text(encoding="utf-8"))
        if any(not e.get("version") or "TBD" in str(e.get("version")) for e in runtime_lock.get("entries") or []):
            return False, "runtime versions are incomplete"
        integrity = runtime_lock.get("integrity")
        if integrity:
            expected = str(integrity.get("uv_lock_sha256") or "")
            if expected != _sha256(uv_lock):
                return False, "runtime lock does not match bundled uv.lock"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"invalid lock data: {exc}"
    return True, "runtime/model/ffmpeg locks parsed and pinned"


def check_release_tree(root: Path) -> tuple[bool, str]:
    runtime = root / "runtime"
    python = runtime / "python.exe"
    site = runtime / "Lib" / "site-packages"
    problems: list[str] = []
    if not python.is_file():
        problems.append("runtime/python.exe missing")
    if (runtime / "pyvenv.cfg").exists():
        problems.append("pyvenv.cfg present")
    if not (site / "qsub_core").is_dir():
        problems.append("qsub_core not installed")
    if not (site / "gui").is_dir():
        problems.append("gui not installed")
    for pth in site.glob("*.pth") if site.is_dir() else []:
        if "editable" in pth.name.lower():
            problems.append(f"editable pth present: {pth.name}")
        for raw in pth.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "import ")):
                continue
            candidate = Path(line)
            if candidate.is_absolute():
                try:
                    candidate.resolve().relative_to(runtime.resolve())
                except ValueError:
                    problems.append(f"external pth path: {line}")
    if problems:
        return False, "; ".join(problems)
    proc = _run(
        [
            str(python),
            "-I",
            "-c",
            "import pathlib,sys,qsub_core,gui; "
            "assert pathlib.Path(sys.base_prefix).resolve()==pathlib.Path(sys.argv[1]).resolve()",
            str(runtime),
        ],
        cwd=root,
    )
    if proc.returncode != 0:
        return False, f"standalone interpreter failed: {(proc.stderr or proc.stdout).strip()[:240]}"
    return True, "standalone CPython; non-editable app; no external .pth paths"


def check_models() -> tuple[bool, str]:
    env = os.environ.copy()
    env.pop("QSUB_ROOT", None)
    proc = _run([sys.executable, str(ROOT / "scripts" / "verify_models.py")], env=env)
    ok = proc.returncode == 0
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.startswith("[")]
    return ok, "; ".join(lines) if lines else f"exit {proc.returncode}"


def check_srt_file(path: Path) -> tuple[bool, str]:
    from qsub_core.subtitles.srt import load_srt, validate_srt_invariants

    if not path.is_file():
        return False, f"missing {path}"
    cues = load_srt(path)
    errors = validate_srt_invariants(cues)
    if errors:
        return False, f"{len(cues)} cues; errors={errors[:5]}"
    return True, f"{len(cues)} cues; 0 invariant errors"


def check_media_e2e(media: Path, *, language: str, device: str) -> tuple[bool, str]:
    env = os.environ.copy()
    env.pop("QSUB_ROOT", None)
    out_dir = Path(tempfile.mkdtemp(prefix="qsub-accept-"))
    srt = out_dir / (media.stem + ".srt")
    work = out_dir / "work"
    cmd = [
        sys.executable,
        "-m",
        "qsub_core.cli",
        "transcribe",
        str(media),
        "--output",
        str(srt),
        "--language",
        language,
        "--device",
        device,
        "--events",
        "ndjson",
        "--work-dir",
        str(work),
        "--overwrite",
        "--keep-work",
    ]
    print("+", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return False, f"transcribe exit {proc.returncode}; work={work}"
    ok, detail = check_srt_file(srt)
    return ok, f"srt={srt}; {detail}"


def _safe_text(value: str) -> str:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return value.encode(enc, errors="replace").decode(enc, errors="replace")


def main() -> int:
    p = argparse.ArgumentParser(description="QwenSubtitle Phase 9 acceptance checks")
    p.add_argument("--media", type=Path, default=None, help="Optional media for e2e transcribe")
    p.add_argument("--language", default="Chinese")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--srt", type=Path, default=None, help="Validate an existing SRT only")
    p.add_argument("--skip-pytest", action="store_true")
    p.add_argument("--release-root", type=Path, default=None, help="Portable/install root to validate")
    p.add_argument("--skip-e2e", action="store_true", help="Skip --media even if provided")
    p.add_argument(
        "--report",
        type=Path,
        default=ROOT / "acceptance" / "last-run.json",
        help="Write machine-readable results JSON",
    )
    args = p.parse_args()

    # Ensure src import path for direct script execution
    sys.path.insert(0, str(ROOT / "src"))

    results: list[dict] = []

    if args.srt:
        ok, detail = check_srt_file(args.srt.resolve())
        results.append({"name": "srt", "ok": ok, "detail": detail})
    else:
        if not args.skip_pytest:
            ok, detail = check_pytest()
            results.append({"name": "pytest", "ok": ok, "detail": detail})
        lock_root = args.release_root.resolve() if args.release_root else ROOT
        ok, detail = check_locks(lock_root)
        results.append({"name": "locks", "ok": ok, "detail": detail})
        if args.release_root:
            ok, detail = check_release_tree(args.release_root.resolve())
            results.append({"name": "release_tree", "ok": ok, "detail": detail})
        ok, detail = check_models()
        results.append({"name": "models", "ok": ok, "detail": detail})
        ok, detail = check_doctor()
        results.append({"name": "doctor", "ok": ok, "detail": detail})
        if args.media and not args.skip_e2e:
            ok, detail = check_media_e2e(
                args.media.resolve(), language=args.language, device=args.device
            )
            results.append({"name": "e2e_transcribe", "ok": ok, "detail": detail})

    print()
    print("=== Acceptance results ===")
    all_ok = True
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        if not r["ok"]:
            all_ok = False
        print(_safe_text(f"[{mark}] {r['name']}: {r['detail']}"))

    report = {
        "schema_version": 1,
        "all_ok": all_ok,
        "results": results,
        "manual": "See acceptance/README.md for GPU/OS/duration/offline matrix",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {args.report}")
    if all_ok:
        print("Automated gates: PASS (complete manual matrix before v0.1 sign-off)")
        return 0
    print("Automated gates: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
