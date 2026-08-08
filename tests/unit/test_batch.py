"""Batch runner unit tests (no ML)."""

from __future__ import annotations

import io
import json
from pathlib import Path

from qsub_core import errors
from qsub_core.events import EventEmitter
from qsub_core.pipeline.batch import (
    BatchRunner,
    BatchSharedOptions,
    collect_input_paths,
    load_manifest,
    resolve_output_path,
)
from qsub_core.pipeline.engine import TranscribeOptions


def test_collect_input_paths_files_and_dir(tmp_path: Path):
    a = tmp_path / "a.wav"
    b = tmp_path / "b.mp4"
    c = tmp_path / "skip.txt"
    sub = tmp_path / "nested"
    sub.mkdir()
    d = sub / "d.mkv"
    for p in (a, b, c, d):
        p.write_bytes(b"x")
    paths = collect_input_paths([a, tmp_path])
    names = {p.name for p in paths}
    assert "a.wav" in names
    assert "b.mp4" in names
    assert "d.mkv" in names
    assert "skip.txt" not in names
    # dedupe
    paths2 = collect_input_paths([a, a])
    assert len(paths2) == 1


def test_resolve_output_path_collision(tmp_path: Path):
    used: set[Path] = set()
    out_dir = tmp_path / "out"
    s1 = tmp_path / "foo.wav"
    s2 = tmp_path / "other" / "foo.mp4"
    s2.parent.mkdir()
    s1.write_bytes(b"1")
    s2.write_bytes(b"2")
    p1 = resolve_output_path(s1, output_dir=out_dir, used=used)
    p2 = resolve_output_path(s2, output_dir=out_dir, used=used)
    assert p1.name == "foo.srt"
    assert p2.name == "foo__2.srt"


def test_load_manifest_json_and_txt(tmp_path: Path):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"inputs": ["a.wav", "b.mp4"]}), encoding="utf-8")
    assert [p.name for p in load_manifest(m)] == ["a.wav", "b.mp4"]
    t = tmp_path / "m.txt"
    t.write_text("# comment\nx.wav\n\ny.mp3\n", encoding="utf-8")
    assert [p.name for p in load_manifest(t)] == ["x.wav", "y.mp3"]


def test_batch_runner_continue_on_error(tmp_path: Path):
    f1 = tmp_path / "one.wav"
    f2 = tmp_path / "two.wav"
    f1.write_bytes(b"1")
    f2.write_bytes(b"2")
    work = tmp_path / "batch-work"
    buf = io.StringIO()
    events = EventEmitter(mode="ndjson", stream=buf)

    codes = {str(f1.resolve()): errors.ASR_FAILURE, str(f2.resolve()): errors.SUCCESS}

    def fake_run(opts: TranscribeOptions, _ev) -> int:
        # Create fake srt on success
        code = codes[str(opts.input_path.resolve())]
        if code == errors.SUCCESS and opts.output is not None:
            opts.output.parent.mkdir(parents=True, exist_ok=True)
            opts.output.write_text("1\n00:00:00,000 --> 00:00:01,000\nok\n", encoding="utf-8")
        return code

    shared = BatchSharedOptions(overwrite=True, stop_on_error=False, events="ndjson")
    runner = BatchRunner(events, shared, run_item=fake_run)
    code = runner.run([f1, f2], work_root=work)
    assert code == 1  # partial failure
    summary = json.loads((work / "batch_summary.json").read_text(encoding="utf-8"))
    assert summary["succeeded"] == 1
    assert summary["failed"] == 1
    types = [json.loads(line)["type"] for line in buf.getvalue().splitlines() if line.strip()]
    assert "batch_started" in types
    assert "batch_completed" in types
    assert types.count("item_finished") == 2


def test_batch_runner_stop_on_error(tmp_path: Path):
    f1 = tmp_path / "one.wav"
    f2 = tmp_path / "two.wav"
    f1.write_bytes(b"1")
    f2.write_bytes(b"2")
    work = tmp_path / "batch-stop"
    events = EventEmitter(mode="ndjson", stream=io.StringIO())

    def fake_run(opts: TranscribeOptions, _ev) -> int:
        return errors.ASR_FAILURE

    shared = BatchSharedOptions(overwrite=True, stop_on_error=True)
    runner = BatchRunner(events, shared, run_item=fake_run)
    code = runner.run([f1, f2], work_root=work)
    assert code == 1
    summary = json.loads((work / "batch_summary.json").read_text(encoding="utf-8"))
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
