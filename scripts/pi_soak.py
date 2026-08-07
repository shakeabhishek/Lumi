"""Soak the LIVE Pi stack — all services concurrent, real hardware.

Different from scripts/phase4_soak.py, which spins up its own throwaway web
app on a laptop with a mock LLM. This one drives the actual deployed stack
(`lumi-web` + `lumi-voice` + `lumi-vision` + `lumi-vision-capture` +
`lumi-openclaw` + `ollama`) while the voice loop is listening and the vision
worker is running the camera, which is the only configuration where cross-
subsystem contention shows up. Run it ON the Pi.

What it watches for, and why each one:

  * **`/chat/stream` hanging under sustained load** — the open bug from
    2026-05-23 (CLAUDE.md's V2 table): a 60-minute soak ran clean for ~11 min
    then piled up 84 ReadTimeouts over the next 49, with no 5xx, no leak, and
    nothing in the logs. Never root-caused. Timeouts are counted separately
    from errors here, and their arrival times are reported, because "when did
    they start" is the diagnostic.
  * **Presence push rate** — regression guard on the 2026-08-05 flicker fix.
    Should sit at the ~12/min heartbeat. A jump back toward 110/min means the
    stillness latch broke.
  * **RSS / FD / thread drift per service** — a leak in any one of five
    long-lived processes.
  * **Thermals** — the sealed-enclosure thermal test is still an open Tier 4
    item, and this is the closest thing to a load test we have.
  * **Tracebacks in any service journal** — the stack is meant to self-heal
    from transient failures, not accumulate them.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import time
from pathlib import Path

import httpx

_RSS_GROWTH_LIMIT_KB = 150 * 1024
_FD_GROWTH_LIMIT = 50
# Heartbeat is one push per 5s => ~12/min. This allows real presence
# transitions on top; a return toward the pre-fix 110/min trips it.
_PRESENCE_PUSHES_PER_MIN_LIMIT = 30
_TEMP_LIMIT_C = 80.0

SERVICES = (
    "lumi-web",
    "lumi-voice",
    "lumi-vision",
    "lumi-vision-capture",
    "lumi-openclaw",
    "ollama",
)

# A realistic mix: native skills (fast, no LLM), and conversational turns that
# go through the router to the LLM. Deliberately includes the skill path so a
# hang can be attributed to one or the other.
PROMPTS = (
    "what time is it",
    "system stats",
    "convert 20 celsius to fahrenheit",
    "what's 15 percent of 240",
    "tell me one short fact about the ocean",
    "volume up",
    "what day is it today",
    "say something brief and cheerful",
)


def _sh(*args: str) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
        return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _service_pids(service: str) -> list[int]:
    """Every PID in the service's cgroup, not just MainPID.

    MainPID for these units is the `uv run` wrapper, which forks the actual
    Python worker — sampling it reported a flat ~37 MB for every service in a
    first smoke run, which is the wrapper's own footprint and tells you nothing
    about the process doing the work. The cgroup is the authoritative set.
    """
    for base in (
        f"/sys/fs/cgroup/system.slice/{service}.service/cgroup.procs",
        f"/sys/fs/cgroup/systemd/system.slice/{service}.service/cgroup.procs",
    ):
        try:
            raw = Path(base).read_text()
        except OSError:
            continue
        pids = [int(x) for x in raw.split() if x.isdigit()]
        if pids:
            return pids
    out = _sh("systemctl", "show", service, "-p", "MainPID", "--value")
    return [int(out)] if out.isdigit() and out != "0" else []


def _proc_sample(pids: list[int]) -> dict[str, int]:
    """Summed across the service's whole process tree."""
    rss = threads = fds = 0
    seen = False
    for pid in pids:
        try:
            status = Path(f"/proc/{pid}/status").read_text()
        except OSError:
            continue
        seen = True
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                rss += int(re.sub(r"\D", "", line) or 0)
            elif line.startswith("Threads:"):
                threads += int(re.sub(r"\D", "", line) or 0)
        try:
            fds += len(list(Path(f"/proc/{pid}/fd").iterdir()))
        except OSError:
            pass
    return {"rss_kb": rss, "threads": threads, "fds": fds} if seen else {}


def _temp_c() -> float:
    raw = _sh("vcgencmd", "measure_temp")
    m = re.search(r"([\d.]+)", raw)
    return float(m.group(1)) if m else 0.0


def _journal_counts(service: str, since: str) -> dict[str, int]:
    log = _sh("journalctl", "-u", service, "--since", since, "--no-pager")
    low = log.lower()
    return {
        "tracebacks": low.count("traceback"),
        "presence_pushes": log.count("/api/presence"),
        "wake_fired": log.count("wake.fired"),
        "barge_in": log.count("barge_in.triggered"),
    }


def _csrf_client(base_url: str) -> httpx.Client:
    # 90s, not 30s: a smoke run measured p50 ~29.8s per turn against a 30s
    # timeout, i.e. the measurement was clipping at the ceiling. The point is
    # to observe real latency, and to make a genuine hang distinguishable from
    # a slow-but-working turn.
    client = httpx.Client(base_url=base_url, timeout=90.0)
    client.get("/")  # mints the csrf_token cookie
    token = client.cookies.get("csrf_token", "")
    client.headers["X-CSRF-Token"] = token
    return client


def run(duration_s: int, interval_s: float, base_url: str) -> int:
    start = time.monotonic()
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    # Absolute, not "now": journalctl --since now means "from when journalctl
    # runs", which is the END of the soak and captures nothing. A first smoke
    # run reported presence_pushes=0 for exactly this reason.
    since = started_at

    pids = {s: _service_pids(s) for s in SERVICES}
    first = {s: _proc_sample(p) for s, p in pids.items()}
    peak: dict[str, dict[str, int]] = {s: dict(v) for s, v in first.items()}

    latencies: list[float] = []
    timeouts: list[float] = []  # elapsed-seconds-into-run for each timeout
    errors: list[str] = []
    turns = 0
    temps: list[float] = []

    client = _csrf_client(base_url)
    print(f"soak start {started_at}  duration={duration_s}s  interval={interval_s}s")
    print(f"  base_url={base_url}")
    print(f"  pids: {pids}")

    try:
        while (elapsed := time.monotonic() - start) < duration_s:
            prompt = PROMPTS[turns % len(PROMPTS)]
            t0 = time.monotonic()
            try:
                with client.stream(
                    "POST", "/chat/stream", data={"message": prompt},
                ) as resp:
                    if resp.status_code >= 400:
                        errors.append(f"{resp.status_code} on {prompt!r}")
                    # Drain the SSE body — the 2026-05-23 hang showed up while
                    # reading, not on connect, so a HEAD-style check would miss it.
                    for _ in resp.iter_lines():
                        pass
                latencies.append(time.monotonic() - t0)
            except httpx.TimeoutException:
                timeouts.append(elapsed)
                print(f"  [{elapsed:7.1f}s] TIMEOUT on {prompt!r}")
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
            turns += 1

            temps.append(_temp_c())
            for s, p in pids.items():
                sample = _proc_sample(p)
                for k, v in sample.items():
                    if v > peak[s].get(k, 0):
                        peak[s][k] = v

            if turns % 20 == 0:
                p50 = statistics.median(latencies) if latencies else 0
                print(
                    f"  [{elapsed:7.1f}s] turns={turns} p50={p50:.2f}s "
                    f"timeouts={len(timeouts)} errors={len(errors)} "
                    f"temp={temps[-1]:.1f}C",
                )
            time.sleep(interval_s)
    finally:
        client.close()

    last = {s: _proc_sample(p) for s, p in pids.items()}
    journals = {s: _journal_counts(s, since) for s in SERVICES}
    alive = {s: _sh("systemctl", "is-active", s) for s in SERVICES}
    minutes = max((time.monotonic() - start) / 60.0, 1e-9)

    # ── report ──────────────────────────────────────────────────────────
    print("\n" + "=" * 68)
    print(f"SOAK REPORT  ({started_at} -> {time.strftime('%Y-%m-%d %H:%M:%S')})")
    print("=" * 68)
    print(f"turns={turns}  timeouts={len(timeouts)}  errors={len(errors)}")
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[int(len(ordered) * 0.95) - 1]
        quarter = max(len(latencies) // 4, 1)
        early = sorted(latencies[:quarter])[int(quarter * 0.95) - 1]
        late = sorted(latencies[-quarter:])[int(quarter * 0.95) - 1]
        drift = late / early if early else 0
        print(
            f"latency  p50={statistics.median(latencies):.2f}s  p95={p95:.2f}s  "
            f"drift(p95 last quarter / first quarter)={drift:.2f}x",
        )
    if temps:
        print(f"temp     max={max(temps):.1f}C  mean={statistics.mean(temps):.1f}C")
    if timeouts:
        print(f"timeouts first at {timeouts[0]:.1f}s, all at: "
              f"{[round(t) for t in timeouts[:20]]}")

    print("\nper-service:")
    for s in SERVICES:
        began, ended, pk = first.get(s, {}), last.get(s, {}), peak.get(s, {})
        if not began or not ended:
            print(f"  {s:<22} (no /proc sample)")
            continue
        print(
            f"  {s:<22} alive={alive[s]:<8} "
            f"rss {began['rss_kb'] // 1024}->{ended['rss_kb'] // 1024}MB "
            f"(peak {pk.get('rss_kb', 0) // 1024}) "
            f"fd {began['fds']}->{ended['fds']}  "
            f"thr {began['threads']}->{ended['threads']}",
        )

    print("\njournals:")
    for s in SERVICES:
        j = journals[s]
        extra = ""
        if s == "lumi-vision":
            rate = j["presence_pushes"] / minutes
            extra = f"  presence_pushes={j['presence_pushes']} ({rate:.1f}/min)"
        print(f"  {s:<22} tracebacks={j['tracebacks']}{extra}")

    # ── verdict ─────────────────────────────────────────────────────────
    fails: list[str] = []
    for s in SERVICES:
        if alive[s] != "active":
            fails.append(f"{s} not active at end ({alive[s]})")
        began, ended = first.get(s, {}), last.get(s, {})
        if began and ended:
            if ended["rss_kb"] > began["rss_kb"] + _RSS_GROWTH_LIMIT_KB:
                fails.append(f"{s} RSS grew {(ended['rss_kb'] - began['rss_kb']) // 1024}MB")
            if ended["fds"] > began["fds"] + _FD_GROWTH_LIMIT:
                fails.append(f"{s} FDs grew {ended['fds'] - began['fds']}")
        if journals[s]["tracebacks"]:
            fails.append(f"{s} logged {journals[s]['tracebacks']} traceback(s)")
    if timeouts:
        fails.append(f"{len(timeouts)} /chat/stream timeout(s) — the 2026-05-23 bug")
    if errors:
        fails.append(f"{len(errors)} request error(s): {errors[:3]}")
    # The flicker-fix regression guard. Heartbeat is 5s => ~12/min; allow slack
    # for real presence transitions during the run.
    pushes_per_min = journals["lumi-vision"]["presence_pushes"] / minutes
    if pushes_per_min > _PRESENCE_PUSHES_PER_MIN_LIMIT:
        fails.append(
            f"presence pushes {pushes_per_min:.1f}/min — stillness latch may have regressed",
        )
    if max(temps, default=0) > _TEMP_LIMIT_C:
        fails.append(f"peak temp {max(temps):.1f}C above 80C")

    print()
    if fails:
        print("VERDICT: FAIL")
        for f_ in fails:
            print(f"  - {f_}")
        return 1
    print("VERDICT: PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--duration", type=int, default=1800, help="seconds (default 1800 = 30 min)")
    ap.add_argument("--interval", type=float, default=6.0, help="seconds between turns")
    ap.add_argument("--base-url", default="http://127.0.0.1", help="live lumi-web")
    ap.add_argument("--report", type=str, default=None, help="also write JSON here")
    args = ap.parse_args()
    rc = run(args.duration, args.interval, args.base_url)
    if args.report:
        Path(args.report).write_text(json.dumps({"exit_code": rc}), encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
