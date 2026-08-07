"""Source fingerprint without hashing entire media (Spec §29)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


DEFAULT_EDGE_BYTES = 1 * 1024 * 1024  # 1 MiB


def source_fingerprint(
    path: Path | str,
    *,
    edge_bytes: int = DEFAULT_EDGE_BYTES,
) -> dict[str, Any]:
    media = Path(path).expanduser().resolve()
    st = media.stat()
    size = int(st.st_size)
    mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))

    head = _hash_range(media, 0, min(edge_bytes, size))
    if size <= edge_bytes:
        tail = head
    else:
        start = max(0, size - edge_bytes)
        tail = _hash_range(media, start, size - start)

    digest = hashlib.sha256(f"{size}:{mtime_ns}:{head}:{tail}".encode("ascii")).hexdigest()
    return {
        "path": str(media),
        "size": size,
        "mtime_ns": mtime_ns,
        "head_sha256": head,
        "tail_sha256": tail,
        "fingerprint": digest,
        "edge_bytes": edge_bytes,
    }


def _hash_range(path: Path, offset: int, length: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        f.seek(offset)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()
