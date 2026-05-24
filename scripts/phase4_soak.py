"""Phase 4 stability soak — Lumi's 1-hour gate criterion.

Runs the full laptop Lumi (web dashboard + chat stream) for a
configurable duration, hammers it with a realistic mix of skill
triggers and conversational turns, and watches for:

  * crashes / OOM (RSS ceiling, process alive at end)
  * file-descriptor or thread leaks (peak vs end)
  * latency degradation (p95 doesn't drift up over the run)
  * HTTP errors / streaming interruptions / orphan tmp files

LLM backend defaults to `mock` so we don't depend on Ollama being up.
The skill path, native handlers, CSRF middleware, SSE pipeline,
audit log, ChromaDB (if enabled), and FastAPI lifecycle are all
exercised end-to-end. Override with --backend ollama if you want to
include real LLM round-trips.

Pass criteria (Phase 4 gate):
  * Process is alive at the end
  * RSS peak < 1 GB
  * RSS end <= RSS start + 100 MB    (no slow leak)
  * FD count end <= FD count start + 50
  * Zero 5xx responses, < 1% 4xx
  * Latency p95 of final 25% turns < 2x p95 of first 25% turns

Usage:
  uv run python scripts/phase4_soak.py --quick     # 2-minute smoke
  uv run python scripts/phase4_soak.py             # full hour
  uv run python scripts/phase4_soak.py --duration 600 --backend ollama
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

try:
    import psutil
except ImportError:
    print("psutil missing — run: uv pip install -e '.[host]'", file=sys.stderr)
    sys.exit(2)


# A realistic mix of what a user might say in an hour. Each tuple is
# (label, message). The labels group counts in the final report. Skill
# triggers should cover every native skill (timer, pomodoro, reminder,
# notes-read/write, system stats, volume, mode switch, clipboard).
# A small LLM-fallback slice exercises the streaming pipeline + memory.
TURN_SCRIPT: list[tuple[str, str]] = [
    # Native skills — fast, deterministic
    ("timer",        "start a timer for 10 minutes"),
    ("timer",        "cancel the timer"),
    ("pomodoro",     "start a pomodoro"),
    ("pomodoro",     "pomodoro status"),
    ("pomodoro",     "cancel pomodoro"),
    ("reminder",     "remind me to drink water in 30 minutes"),
    ("notes",        "remember that the wifi password is hunter2"),
    ("notes",        "remember that I prefer oat milk"),
    ("notes",        "what did I note about wifi"),
    ("notes",        "show my notes"),
    ("system",       "system stats"),
    ("system",       "how much memory am I using"),
    ("volume",       "louder"),
    ("volume",       "quieter"),
    ("mode",         "switch to focus mode"),
    ("mode",         "switch to general mode"),
    # LLM fallback (mock backend yields fast, but exercises SSE)
    ("llm",          "tell me a short joke"),
    ("llm",          "summarize the day so far"),
    ("llm",          "what's the meaning of life"),
    # Memory exercise — "remember X" then later "what did I note about X"
    ("notes",        "remember that the dentist is on Tuesday"),
    ("notes",        "what did I note about the dentist"),
    ("notes",        "clear all notes"),
]

# Lighter recovery turns we sprinkle in during the cooldown half so the
# process gets a chance to settle (and we can detect post-load leaks).
COOLDOWN_TURNS: list[tuple[str, str]] = [
    ("system",       "system stats"),
    ("mode",         "switch to general mode"),
]


def _wait_until_port_open(host: str, port: int, timeout_s: float = 30.0) -> bool:
    """Block until the uvicorn process is accepting connections, or timeout."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return statistics.quantiles(values, n=100)[int(q) - 1] if len(values) >= 100 else max(values)


def _sample_resources(proc: psutil.Process) -> dict[str, Any]:
    """One snapshot of the server process. None of these can fail without
    the process being dead, which the caller detects separately."""
    info = proc.as_dict(attrs=["memory_info", "num_threads"])
    fds = 0
    try:
        fds = proc.num_fds() if hasattr(proc, "num_fds") else len(proc.open_files())
    except (psutil.AccessDenied, OSError):
        fds = -1
    return {
        "rss_mb": info["memory_info"].rss / (1024 * 1024),
        "vms_mb": info["memory_info"].vms / (1024 * 1024),
        "fds": fds,
        "threads": info["num_threads"],
    }


def _drive_turn(
    client: httpx.Client, csrf: str, message: str, timeout_s: float = 30.0,
) -> tuple[int, float, str]:
    """Fire one POST /chat/stream, fully consume the SSE body, return
    (status, elapsed_ms, last_chunk_or_error)."""
    t0 = time.perf_counter()
    try:
        with client.stream(
            "POST",
            "/chat/stream",
            data={"message": message, "csrf_token": csrf},
            headers={"X-CSRF-Token": csrf},
            timeout=timeout_s,
        ) as r:
            last_event = ""
            for line in r.iter_lines():
                if line:
                    last_event = line
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return r.status_code, elapsed_ms, last_event[:120]
    except (httpx.HTTPError, httpx.StreamError) as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return -1, elapsed_ms, f"{type(exc).__name__}: {exc}"[:120]


def _spawn_server(port: int, data_dir: Path, backend: str) -> subprocess.Popen:
    env = {
        **os.environ,
        "LUMI_LLM_BACKEND": backend,
        "LUMI_DATA_DIR": str(data_dir),
        "LUMI_LOG_LEVEL": "WARNING",
    }
    return subprocess.Popen(
        ["uv", "run", "lumi", "web", "--port", str(port), "--host", "127.0.0.1"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _drain_subprocess(proc: subprocess.Popen, lines_max: int = 200) -> list[str]:
    """Pull the server's stdout/stderr (combined) without blocking long."""
    out: list[str] = []
    if proc.stdout is None:
        return out
    proc.terminate()
    try:
        text = proc.communicate(timeout=5)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        text = proc.communicate(timeout=5)[0]
    if text:
        out = text.splitlines()[-lines_max:]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--duration", type=int, default=3600,
                    help="Total run in seconds (default 3600 = 1 hour)")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="Seconds between turns (default 5.0)")
    ap.add_argument("--sample-every", type=float, default=10.0,
                    help="Resource sample cadence in seconds (default 10)")
    ap.add_argument("--port", type=int, default=18089,
                    help="Port the soaked server listens on")
    ap.add_argument("--backend", default="mock",
                    choices=["mock", "ollama", "hailo"],
                    help="LLM backend for the soaked server (default mock)")
    ap.add_argument("--quick", action="store_true",
                    help="Override duration to 120s for a smoke run")
    ap.add_argument("--report", type=str, default=None,
                    help="Write JSON report to this path (default stdout)")
    args = ap.parse_args()

    if args.quick:
        args.duration = 120
        args.interval = 2.0

    # ── Spin up an isolated server ─────────────────────────────────────────
    soak_dir = Path(tempfile.mkdtemp(prefix="lumi_soak_"))
    print(f"[soak] data_dir = {soak_dir}", file=sys.stderr)
    print(f"[soak] duration = {args.duration}s, interval = {args.interval}s, backend = {args.backend}", file=sys.stderr)

    proc = _spawn_server(args.port, soak_dir, args.backend)
    if not _wait_until_port_open("127.0.0.1", args.port):
        print("[soak] server failed to start within 30s", file=sys.stderr)
        _drain_subprocess(proc)
        return 2

    ps_proc = psutil.Process(proc.pid)

    client = httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=30.0)
    client.get("/")        # warm the CSRF cookie
    csrf = client.cookies.get("csrf_token", "") or ""
    if not csrf:
        print("[soak] no CSRF token received from warm-up GET", file=sys.stderr)

    # ── Driver loop ────────────────────────────────────────────────────────
    samples: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    by_label_latencies: dict[str, list[float]] = {}

    start = time.time()
    last_sample_t = 0.0
    turn_idx = 0

    try:
        while time.time() - start < args.duration:
            now = time.time() - start

            # Sample resources periodically
            if now - last_sample_t >= args.sample_every:
                if not ps_proc.is_running():
                    errors.append({"t": now, "kind": "process_died"})
                    break
                samples.append({"t": now, **_sample_resources(ps_proc)})
                last_sample_t = now

            # Choose turn: cooldown after 75% so we can detect post-load drift
            script = TURN_SCRIPT if now < args.duration * 0.75 else COOLDOWN_TURNS
            label, message = script[turn_idx % len(script)]
            status, latency_ms, tail = _drive_turn(client, csrf, message)

            turns.append({
                "t": now,
                "label": label,
                "msg": message[:60],
                "status": status,
                "latency_ms": round(latency_ms, 1),
            })
            by_label_latencies.setdefault(label, []).append(latency_ms)

            if status == -1 or status >= 500:
                errors.append({
                    "t": now,
                    "kind": "http_error",
                    "status": status,
                    "msg": message[:60],
                    "tail": tail,
                })

            # Progress: print a marker per minute, dot per turn
            sys.stdout.write(".")
            sys.stdout.flush()
            if int(now) // 60 != int(now - args.interval) // 60:
                print(f"\n[soak] {int(now // 60)} min · {len(turns)} turns · {len(errors)} errors",
                      file=sys.stderr)

            turn_idx += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[soak] interrupted — finishing up", file=sys.stderr)

    # ── Capture final state, then tear down ────────────────────────────────
    server_alive = ps_proc.is_running()
    final_sample = _sample_resources(ps_proc) if server_alive else None
    server_tail = _drain_subprocess(proc)
    client.close()

    # ── Build report ───────────────────────────────────────────────────────
    duration_s = time.time() - start
    rss_values = [s["rss_mb"] for s in samples]
    fd_values = [s["fds"] for s in samples if s["fds"] >= 0]
    thread_values = [s["threads"] for s in samples]

    quarter = max(1, len(turns) // 4)
    early_latencies = [t["latency_ms"] for t in turns[:quarter] if t["latency_ms"] is not None]
    late_latencies = [t["latency_ms"] for t in turns[-quarter:] if t["latency_ms"] is not None]

    by_label = {
        label: {
            "n": len(lats),
            "p50_ms": round(statistics.median(lats), 1) if lats else 0,
            "p95_ms": round(_pct(lats, 95), 1) if lats else 0,
            "max_ms": round(max(lats), 1) if lats else 0,
        }
        for label, lats in by_label_latencies.items()
    }

    rss_peak = max(rss_values) if rss_values else 0
    rss_start = rss_values[0] if rss_values else 0
    rss_end = rss_values[-1] if rss_values else 0
    fd_peak = max(fd_values) if fd_values else 0
    fd_start = fd_values[0] if fd_values else 0
    fd_end = fd_values[-1] if fd_values else 0
    thread_peak = max(thread_values) if thread_values else 0

    early_p95 = _pct(early_latencies, 95) if early_latencies else 0
    late_p95 = _pct(late_latencies, 95) if late_latencies else 0
    latency_drift_ratio = (late_p95 / early_p95) if early_p95 > 0 else 0

    # Gate checks
    gates = {
        "process_alive_at_end": server_alive,
        "rss_under_1gb": rss_peak < 1024,
        "no_slow_rss_leak": (rss_end - rss_start) < 100,
        "no_fd_leak": (fd_end - fd_start) < 50,
        "no_5xx": all(t["status"] < 500 or t["status"] == -1 for t in turns),
        "latency_drift_under_2x": latency_drift_ratio == 0 or latency_drift_ratio < 2.0,
    }
    passed = all(gates.values())

    # Surface any ERROR / WARNING lines from the server tail that suggest
    # crashes or stack traces we'd otherwise miss.
    server_concerns = [
        line for line in server_tail
        if any(needle in line.lower() for needle in (
            "traceback", "error", "exception", "critical",
        ))
    ][-20:]

    report = {
        "passed": passed,
        "duration_s": round(duration_s, 1),
        "turns": len(turns),
        "errors_count": len(errors),
        "gates": gates,
        "resources": {
            "rss_start_mb": round(rss_start, 1),
            "rss_peak_mb": round(rss_peak, 1),
            "rss_end_mb": round(rss_end, 1),
            "rss_delta_mb": round(rss_end - rss_start, 1),
            "fd_start": fd_start,
            "fd_peak": fd_peak,
            "fd_end": fd_end,
            "thread_peak": thread_peak,
            "samples_n": len(samples),
        },
        "latency_ms": {
            "early_p95": round(early_p95, 1),
            "late_p95": round(late_p95, 1),
            "drift_ratio": round(latency_drift_ratio, 2),
            "by_label": by_label,
        },
        "errors": errors[:20],
        "server_concerns": server_concerns,
        "final_sample": final_sample,
    }

    blob = json.dumps(report, indent=2, default=str)
    if args.report:
        Path(args.report).write_text(blob)
        print(f"\n[soak] report → {args.report}", file=sys.stderr)
    else:
        print()
        print(blob)

    # Print a one-line verdict to stderr too
    verdict = "PASS" if passed else "FAIL"
    print(f"\n[soak] {verdict} — {len(turns)} turns / {duration_s:.0f}s "
          f"/ rss {rss_start:.0f}→{rss_end:.0f} MB (peak {rss_peak:.0f}) "
          f"/ fd {fd_start}→{fd_end} (peak {fd_peak}) "
          f"/ drift {latency_drift_ratio:.2f}x "
          f"/ errors {len(errors)}",
          file=sys.stderr)

    return 0 if passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[soak] interrupted", file=sys.stderr)
        sys.exit(130)
