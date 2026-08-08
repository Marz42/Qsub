#!/usr/bin/env python3
"""
Phase 9 acceptance gate (Spec §54–§55).

Automated checks for the current machine/release tree. Hardware matrix rows
(RTX 30, Win10, 60 min, …) remain manual — see acceptance/README.md.
"""

from __future__ import annotations

import argparse
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


def check_locks() -> tuple[bool, str]:
    required = [
        ROOT / "uv.lock",
        ROOT / "manifests" / "runtime-lock.json",
        ROOT / "manifests" / "model-lock.json",
        ROOT / "manifests" / "ffmpeg-lock.json",
        ROOT / "manifests" / "licenses.json",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
    if missing:
        return False, "missing: " + ", ".join(missing)
    return True, "uv.lock + runtime/model/ffmpeg/licenses locks present"


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
        ok, detail = check_locks()
        results.append({"name": "locks", "ok": ok, "detail": detail})
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
