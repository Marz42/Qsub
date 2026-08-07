"""Minimal CLI entry (Phase 1 will expand)."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("qsub — QwenSubtitle CLI (Phase 0: use scripts/phase0_spike.py)")
        print("Coming in Phase 1: doctor | probe | transcribe | export")
        return 0
    print(f"Unknown command: {argv[0]!r}. Phase 1 CLI not implemented yet.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
