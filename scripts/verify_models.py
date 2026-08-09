#!/usr/bin/env python3
"""Verify local model files against manifests/model-lock.json (when hashes present)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qsub_core.model_store import validate_model_dir

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "manifests" / "model-lock.json"


def main() -> int:
    p = argparse.ArgumentParser(description="Verify models exist (and sha256 when locked)")
    p.add_argument("--lock", type=Path, default=LOCK)
    p.add_argument("--root", type=Path, default=ROOT)
    args = p.parse_args()

    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    entries = lock.get("entries") or []
    ok = True
    for entry in entries:
        rel = entry.get("local_path")
        if not rel:
            continue
        path = args.root / rel
        result = validate_model_dir(path, entry, verify_hashes=True)
        status = "OK" if result["ok"] else "INVALID"
        print(f"[{status}] {entry.get('name')} → {path}")
        if not result["ok"]:
            for issue in result["issues"]:
                print(f"  {issue}")
            ok = False
        else:
            print(f"  revision={entry.get('revision')} hashes=OK")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
