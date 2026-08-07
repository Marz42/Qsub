"""Overlap merge unit tests."""

from __future__ import annotations

from qsub_core.alignment.merge import merge_global_tokens


def test_overlap_dedupe_by_text_suffix_prefix():
    chunks = [
        {"id": 0, "start": 0.0, "end": 10.0, "overlap_before": 0.0},
        {"id": 1, "start": 9.0, "end": 20.0, "overlap_before": 1.0},
    ]
    records = [
        {
            "chunk_id": 0,
            "start": 0.0,
            "end": 10.0,
            "items": [
                {"text": "这是", "start": 8.0, "end": 8.5},
                {"text": "一个", "start": 8.5, "end": 9.0},
                {"text": "测试", "start": 9.0, "end": 9.5},
            ],
        },
        {
            "chunk_id": 1,
            "start": 9.0,
            "end": 20.0,
            "overlap_before": 1.0,
            "items": [
                {"text": "一个", "start": 0.0, "end": 0.4},  # global 9.0
                {"text": "测试", "start": 0.4, "end": 0.8},  # global 9.4
                {"text": "继续", "start": 1.0, "end": 1.4},  # global 10.0
            ],
        },
    ]
    tokens = merge_global_tokens(records, chunks)
    texts = [t["text"] for t in tokens]
    # Duplicate "一个""测试" from chunk1 should be dropped
    assert texts.count("一个") == 1
    assert texts.count("测试") == 1
    assert "继续" in texts
    for i in range(1, len(tokens)):
        assert tokens[i]["start"] + 1e-9 >= tokens[i - 1]["start"]
