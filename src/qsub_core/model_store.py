"""Pinned model registry and local model integrity helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from qsub_core.config import install_root

MODEL_MARKER = ".qsub-model.json"


def model_lock_path() -> Path:
    return install_root() / "manifests" / "model-lock.json"


def load_model_lock(path: Path | None = None) -> dict[str, Any]:
    lock_path = path or model_lock_path()
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    if int(data.get("schema_version", 0)) != 1 or not isinstance(data.get("entries"), list):
        raise ValueError(f"invalid model lock: {lock_path}")
    return data


def model_entry(name: str, *, lock: dict[str, Any] | None = None) -> dict[str, Any]:
    data = lock or load_model_lock()
    for entry in data.get("entries") or []:
        if entry.get("name") == name:
            return entry
    raise KeyError(f"model not present in lock: {name}")


def model_revision(name: str) -> str:
    return str(model_entry(name).get("revision") or "unknown")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def detected_revision(path: Path) -> str | None:
    marker = path / MODEL_MARKER
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            revision = data.get("revision")
            return str(revision) if revision else None
        except (OSError, json.JSONDecodeError):
            return None
    metadata = path / ".cache" / "huggingface" / "download" / "config.json.metadata"
    if metadata.is_file():
        try:
            first = metadata.read_text(encoding="utf-8").splitlines()[0].strip()
            return first or None
        except (OSError, IndexError):
            return None
    return None


def validate_model_dir(
    path: Path,
    entry: dict[str, Any],
    *,
    verify_hashes: bool = False,
) -> dict[str, Any]:
    issues: list[str] = []
    expected_revision = str(entry.get("revision") or "")
    actual_revision = detected_revision(path) if path.is_dir() else None
    if not path.is_dir():
        issues.append("directory missing")
    for item in entry.get("required_files") or []:
        rel = Path(str(item.get("path") or ""))
        candidate = path / rel
        if not candidate.is_file():
            issues.append(f"missing {rel.as_posix()}")
            continue
        expected_size = item.get("size")
        if expected_size is not None and candidate.stat().st_size != int(expected_size):
            issues.append(f"size mismatch {rel.as_posix()}")
            continue
        expected_hash = str(item.get("sha256") or "")
        if verify_hashes and expected_hash and sha256_file(candidate).lower() != expected_hash.lower():
            issues.append(f"sha256 mismatch {rel.as_posix()}")
    if expected_revision and actual_revision and actual_revision != expected_revision:
        issues.append(f"revision mismatch expected={expected_revision} actual={actual_revision}")
    return {
        "ok": not issues,
        "path": str(path),
        "revision": actual_revision,
        "expected_revision": expected_revision or None,
        "revision_verified": bool(actual_revision and actual_revision == expected_revision),
        "hashes_verified": bool(verify_hashes and not issues),
        "issues": issues,
    }


def write_model_marker(path: Path, entry: dict[str, Any]) -> None:
    marker = path / MODEL_MARKER
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": entry.get("name"),
                "revision": entry.get("revision"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
