#!/usr/bin/env python3
"""Phase 0 model spike: WAV → ASR → ForcedAligner → JSON (Safe Mode).

Acceptance (Spec §54 Phase 0):
  5–10 minute Chinese / English WAV runs end-to-end and writes JSON artifacts.

Does NOT implement VAD (Phase 2). Uses Spec chunk defaults with simple time cuts
so ForcedAligner stays under its ~5 minute / hard_max 240s limit.

Safe Mode (Spec §7):
  Phase A — load ASR only → all chunks → unload + empty CUDA cache
  Phase B — load ForcedAligner only → all chunks → unload
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

# Allow running without editable install
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from qsub_core import errors
from qsub_core.io_util import atomic_write_json
from qsub_core.pipeline.chunk_plan import (
    HARD_MAX_DURATION,
    ChunkPlan,
    plan_chunks,
)


def _repo_root() -> Path:
    return _ROOT


def _default_model(env_key: str, relative: str) -> Path:
    override = os.environ.get(env_key)
    if override:
        return Path(override).expanduser().resolve()
    return (_repo_root() / relative).resolve()


def _require_local_model(path: Path, label: str) -> None:
    if not path.exists():
        print(
            f"[error] {label} not found: {path}\n"
            f"Place the model under models/ (see models/README.md) "
            f"or set the corresponding env var.",
            file=sys.stderr,
        )
        raise SystemExit(errors.MODEL_MISSING)
    if not any(path.iterdir()):
        print(f"[error] {label} directory is empty: {path}", file=sys.stderr)
        raise SystemExit(errors.MODEL_MISSING)


def _load_mono_wav(path: Path) -> tuple[np.ndarray, int, float]:
    wav, sr = sf.read(str(path), dtype="float32", always_2d=False)
    wav = np.asarray(wav, dtype=np.float32)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    duration = float(len(wav) / sr)
    return wav, int(sr), duration


def _slice_wav(wav: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    i0 = int(round(start * sr))
    i1 = int(round(end * sr))
    i0 = max(0, min(i0, len(wav)))
    i1 = max(i0, min(i1, len(wav)))
    return wav[i0:i1].copy()


def _empty_cuda() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _pick_device(requested: str) -> str:
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        if not torch.cuda.is_available():
            print("[error] --device cuda but torch.cuda.is_available() is False", file=sys.stderr)
            raise SystemExit(errors.CUDA_UNAVAILABLE)
        return "cuda:0"
    # auto
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def _dtype_for(device: str) -> torch.dtype:
    # bfloat16 is preferred on modern NVIDIA; float32 on CPU.
    if device.startswith("cuda"):
        return torch.bfloat16
    return torch.float32


def run_phase_a_asr(
    *,
    asr_path: Path,
    device: str,
    chunks: list[ChunkPlan],
    wav: np.ndarray,
    sr: int,
    language: str | None,
    out_asr: Path,
) -> list[dict]:
    from qwen_asr import Qwen3ASRModel

    print(f"[phase-a] loading ASR from {asr_path} on {device} ...")
    t0 = time.perf_counter()
    model = Qwen3ASRModel.from_pretrained(
        str(asr_path),
        dtype=_dtype_for(device),
        device_map=device,
        max_inference_batch_size=1,
        max_new_tokens=512,
    )
    print(f"[phase-a] ASR loaded in {time.perf_counter() - t0:.1f}s")

    results: list[dict] = []
    try:
        for ch in chunks:
            audio = _slice_wav(wav, sr, ch.start, ch.end)
            print(
                f"[phase-a] ASR chunk {ch.id:06d} "
                f"{ch.start:.2f}->{ch.end:.2f}s ({len(audio) / sr:.1f}s audio)"
            )
            t1 = time.perf_counter()
            try:
                outs = model.transcribe(
                    audio=(audio, sr),
                    language=language,
                    return_time_stamps=False,
                )
            except torch.cuda.OutOfMemoryError:
                print("[error] CUDA OOM during ASR", file=sys.stderr)
                raise SystemExit(errors.CUDA_OOM) from None

            out = outs[0]
            record = {
                "chunk_id": ch.id,
                "start": ch.start,
                "end": ch.end,
                "overlap_before": ch.overlap_before,
                "language": getattr(out, "language", None),
                "text": getattr(out, "text", "") or "",
                "model": "Qwen3-ASR-0.6B",
                "elapsed_seconds": round(time.perf_counter() - t1, 3),
            }
            path = out_asr / f"{ch.id:06d}.json"
            atomic_write_json(path, record)
            results.append(record)
            print(
                f"[phase-a]   lang={record['language']!r} "
                f"chars={len(record['text'])} "
                f"in {record['elapsed_seconds']}s"
            )
    finally:
        print("[phase-a] unloading ASR ...")
        del model
        _empty_cuda()

    return results


def run_phase_b_align(
    *,
    aligner_path: Path,
    device: str,
    chunks: list[ChunkPlan],
    wav: np.ndarray,
    sr: int,
    asr_results: list[dict],
    out_align: Path,
) -> list[dict]:
    from qwen_asr import Qwen3ForcedAligner

    by_id = {r["chunk_id"]: r for r in asr_results}
    print(f"[phase-b] loading ForcedAligner from {aligner_path} on {device} ...")
    t0 = time.perf_counter()
    aligner = Qwen3ForcedAligner.from_pretrained(
        str(aligner_path),
        dtype=_dtype_for(device),
        device_map=device,
    )
    print(f"[phase-b] Aligner loaded in {time.perf_counter() - t0:.1f}s")

    results: list[dict] = []
    try:
        for ch in chunks:
            asr = by_id[ch.id]
            text = (asr.get("text") or "").strip()
            language = asr.get("language") or "Chinese"
            audio = _slice_wav(wav, sr, ch.start, ch.end)

            if not text:
                record = {
                    "chunk_id": ch.id,
                    "start": ch.start,
                    "end": ch.end,
                    "language": language,
                    "items": [],
                    "warning": "empty_asr_text",
                    "model": "Qwen3-ForcedAligner-0.6B",
                }
                atomic_write_json(out_align / f"{ch.id:06d}.json", record)
                results.append(record)
                print(f"[phase-b] align chunk {ch.id:06d} skipped (empty ASR text)")
                continue

            print(
                f"[phase-b] align chunk {ch.id:06d} "
                f"{ch.start:.2f}->{ch.end:.2f}s text_len={len(text)}"
            )
            t1 = time.perf_counter()
            try:
                outs = aligner.align(
                    audio=(audio, sr),
                    text=text,
                    language=language,
                )
            except torch.cuda.OutOfMemoryError:
                print("[error] CUDA OOM during alignment", file=sys.stderr)
                raise SystemExit(errors.CUDA_OOM) from None

            items_raw = outs[0]
            items = []
            for it in items_raw:
                items.append(
                    {
                        "text": getattr(it, "text", ""),
                        "start": float(getattr(it, "start_time")),
                        "end": float(getattr(it, "end_time")),
                    }
                )

            record = {
                "chunk_id": ch.id,
                "start": ch.start,
                "end": ch.end,
                "language": language,
                "items": items,
                "model": "Qwen3-ForcedAligner-0.6B",
                "elapsed_seconds": round(time.perf_counter() - t1, 3),
            }
            atomic_write_json(out_align / f"{ch.id:06d}.json", record)
            results.append(record)
            print(f"[phase-b]   tokens={len(items)} in {record['elapsed_seconds']}s")
    finally:
        print("[phase-b] unloading ForcedAligner ...")
        del aligner
        _empty_cuda()

    return results


def _merge_global_tokens(align_results: list[dict]) -> list[dict]:
    """Map local chunk timestamps to global timeline (no overlap dedupe yet)."""
    tokens: list[dict] = []
    for rec in sorted(align_results, key=lambda r: r["chunk_id"]):
        base = float(rec["start"])
        for it in rec.get("items") or []:
            tokens.append(
                {
                    "text": it["text"],
                    "start": round(base + float(it["start"]), 3),
                    "end": round(base + float(it["end"]), 3),
                    "chunk_id": rec["chunk_id"],
                }
            )
    return tokens


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 0 spike: local WAV → ASR → ForcedAligner → JSON (Safe Mode)",
    )
    p.add_argument("wav", type=Path, help="Input WAV (prefer 16 kHz mono PCM)")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=_repo_root() / "spikes" / "phase0" / "out",
        help="Output directory for JSON artifacts",
    )
    p.add_argument(
        "--asr-model",
        type=Path,
        default=_default_model("QSUB_ASR_MODEL", "models/Qwen3-ASR-0.6B"),
    )
    p.add_argument(
        "--aligner-model",
        type=Path,
        default=_default_model("QSUB_ALIGNER_MODEL", "models/Qwen3-ForcedAligner-0.6B"),
    )
    p.add_argument(
        "--language",
        default="auto",
        help="auto | Chinese | English | Japanese | ...",
    )
    p.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    p.add_argument(
        "--hard-max-duration",
        type=float,
        default=HARD_MAX_DURATION,
        help="Max chunk length seconds (ForcedAligner safety margin)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    wav_path = args.wav.expanduser().resolve()
    if not wav_path.is_file():
        print(f"[error] WAV not found: {wav_path}", file=sys.stderr)
        return errors.INVALID_INPUT

    hard_max = float(args.hard_max_duration)

    _require_local_model(args.asr_model, "ASR model")
    _require_local_model(args.aligner_model, "ForcedAligner model")

    device = _pick_device(args.device)
    language = None if args.language.lower() == "auto" else args.language

    print(f"[spike] wav={wav_path}")
    print(f"[spike] device={device} torch={torch.__version__} cuda={torch.cuda.is_available()}")
    print(f"[spike] asr={args.asr_model}")
    print(f"[spike] aligner={args.aligner_model}")

    wav, sr, duration = _load_mono_wav(wav_path)
    print(f"[spike] audio sr={sr} duration={duration:.2f}s ({duration / 60:.2f} min)")

    chunks = plan_chunks(duration, hard_max=hard_max)
    print(f"[spike] chunks={len(chunks)} (hard_max={hard_max}s, VAD not used in Phase 0)")

    out_dir = args.out_dir.expanduser().resolve()
    out_asr = out_dir / "asr"
    out_align = out_dir / "alignment"
    out_asr.mkdir(parents=True, exist_ok=True)
    out_align.mkdir(parents=True, exist_ok=True)

    job = {
        "schema_version": 1,
        "phase": "phase0_spike",
        "mode": "safe",
        "source": {
            "path": str(wav_path),
            "sample_rate": sr,
            "duration": duration,
        },
        "device": device,
        "language_request": args.language,
        "chunks": [c.to_dict() for c in chunks],
    }
    atomic_write_json(out_dir / "job.json", job)
    atomic_write_json(out_dir / "chunks.json", {"version": 1, "chunks": [c.to_dict() for c in chunks]})

    wall0 = time.perf_counter()
    asr_results = run_phase_a_asr(
        asr_path=args.asr_model.resolve(),
        device=device,
        chunks=chunks,
        wav=wav,
        sr=sr,
        language=language,
        out_asr=out_asr,
    )
    align_results = run_phase_b_align(
        aligner_path=args.aligner_model.resolve(),
        device=device,
        chunks=chunks,
        wav=wav,
        sr=sr,
        asr_results=asr_results,
        out_align=out_align,
    )

    tokens = _merge_global_tokens(align_results)
    result = {
        "schema_version": 1,
        "phase": "phase0_spike",
        "mode": "safe",
        "source": job["source"],
        "recognition": {
            "model": "Qwen3-ASR-0.6B",
            "language": asr_results[0].get("language") if asr_results else None,
        },
        "alignment": {"model": "Qwen3-ForcedAligner-0.6B"},
        "chunks": [c.to_dict() for c in chunks],
        "asr": asr_results,
        "alignment_chunks": align_results,
        "tokens": tokens,
        "elapsed_seconds": round(time.perf_counter() - wall0, 3),
        "notes": [
            "Phase 0 spike only — no VAD, no timestamp repair, no SRT export.",
            "Overlap dedupe deferred to Phase 4.",
        ],
    }
    out_json = out_dir / "spike_result.json"
    atomic_write_json(out_json, result)

    print(f"[spike] done in {result['elapsed_seconds']}s")
    print(f"[spike] wrote {out_json}")
    print(f"[spike] tokens={len(tokens)} asr_chunks={len(asr_results)}")
    return errors.SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
