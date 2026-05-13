"""Tests for PipelineTimer and PerfLog."""

from __future__ import annotations

import json
import time
from pathlib import Path

from lumi.runtime.perf import PerfLog, PipelineTimer


def test_timer_marks_stages() -> None:
    t = PipelineTimer()
    time.sleep(0.01)
    t.mark("stt_ms")
    time.sleep(0.01)
    t.mark("router_ms")
    summary = t.summary()
    assert "stt_ms" in summary
    assert "router_ms" in summary
    assert summary["router_ms"] > summary["stt_ms"]


def test_timer_total_ms() -> None:
    t = PipelineTimer()
    t.mark("a")
    t.mark("b")
    assert t.total_ms() == max(t.summary().values())


def test_timer_log_line_contains_stages() -> None:
    t = PipelineTimer()
    t.mark("stt_ms")
    line = t.log_line()
    assert "stt_ms" in line
    assert "total=" in line


def test_perf_log_record_and_read(tmp_path: Path) -> None:
    log = PerfLog(tmp_path)
    t = PipelineTimer()
    t.mark("stt_ms")
    t.mark("router_ms")
    log.record(t)
    entries = log.get_recent(n=10)
    assert len(entries) == 1
    assert "ts" in entries[0]
    assert "total_ms" in entries[0]
    assert "stt_ms" in entries[0]


def test_perf_log_most_recent_first(tmp_path: Path) -> None:
    log = PerfLog(tmp_path)
    for _ in range(5):
        t = PipelineTimer()
        t.mark("stt_ms")
        log.record(t)
    entries = log.get_recent(n=3)
    assert len(entries) == 3
    # Most recent first — timestamps should be non-increasing
    assert entries[0]["ts"] >= entries[-1]["ts"]


def test_perf_log_empty_returns_empty(tmp_path: Path) -> None:
    log = PerfLog(tmp_path)
    assert log.get_recent() == []


def test_perf_log_trims_to_max(tmp_path: Path) -> None:
    log = PerfLog(tmp_path)
    log.MAX_LINES = 10
    for _ in range(15):
        t = PipelineTimer()
        t.mark("x")
        log.record(t)
    entries = log.get_recent(n=100)
    assert len(entries) <= 10


def test_perf_log_handles_corrupt_line(tmp_path: Path) -> None:
    log = PerfLog(tmp_path)
    p = tmp_path / "perf.jsonl"
    p.write_text('{"ts": 1}\nnot json\n{"ts": 2}\n')
    entries = log.get_recent(n=10)
    assert len(entries) == 2
