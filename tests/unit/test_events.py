"""Event protocol unit tests."""

from __future__ import annotations

import io
import json

from qsub_core.events import EventEmitter


def test_ndjson_event_has_version():
    buf = io.StringIO()
    em = EventEmitter(mode="ndjson", stream=buf)
    em.emit("job_started", job_id="abc")
    line = buf.getvalue().strip()
    obj = json.loads(line)
    assert obj["v"] == 1
    assert obj["type"] == "job_started"
    assert obj["job_id"] == "abc"


def test_text_mode_writes_human_line():
    out = io.StringIO()
    err = io.StringIO()
    em = EventEmitter(mode="text", stream=out, text_stream=err)
    em.emit("progress", stage="asr", current=1, total=2, overall=0.5)
    assert "progress" in err.getvalue()
    assert out.getvalue() == ""
