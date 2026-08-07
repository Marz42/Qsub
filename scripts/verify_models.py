#!/usr/bin/env python3
"""Verify local model files against manifests/model-lock.json (when hashes present)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "manifests" / "model-lock.json"


def sha256_tree(path: Path) -> str | None:
    """Hash a single file, or None for directories (directory hash not used yet)."""
    if path.is_file():
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    return None


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
        exists = path.exists() and (path.is_file() or (path.is_dir() and any(path.iterdir())))
        status = "OK" if exists else "MISSING"
        print(f"[{status}] {entry.get('name')} → {path}")
        if not exists:
            ok = False
            continue
        expected = entry.get("sha256")
        if expected and path.is_file():
            actual = sha256_tree(path)
            if actual != expected:
                print(f"  HASH MISMATCH expected={expected} actual={actual}")
                ok = False
            else:
                print("  hash OK")
        elif expected and path.is_dir():
            print("  note: directory sha256 not verified (record file-level hashes for release)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
