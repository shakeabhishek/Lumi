"""End-to-end demo / pre-flight smoke test for laptop Lumi.

Walks the full chat surface — what the voice loop would do on the
Pi, minus the audio capture (we hand the transcript directly to
/chat/stream). Captures the device-display SSE feed in a background
thread so we can verify face-state transitions actually fire.

Use this:
  * Before sending a feature branch off for review — a one-shot
    "is the dashboard still wired together end-to-end?" check
  * As a baseline to diff against the first time the Pi runs the
    same prompts on real hardware
  * After any change to chat/stream, the device-display SSE bus, or
    the audit log shape

Usage:
  uv run python scripts/demo_loop.py
  uv run python scripts/demo_loop.py --backend ollama   # exercise real LLM round-trips
  uv run python scripts/demo_loop.py --port 18099       # avoid colliding with a running lumi web
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


# A small representative mix. Each tuple is (label, message, expected_handler).
# expected_handler is what audit log should say — used to flag regressions
# at a glance. None means "we don't care which path served it".
DEMO_PROMPTS: list[tuple[str, str, str | None]] = [
    ("native:timer",       "set a timer for 1 minute",                     "native"),
    ("native:todo-add",    "todo: ship the demo script",                   "native"),
    ("native:todo-list",   "what's on my todo list",                       "native"),
    ("native:notes-add",   "remember that I take oat milk in my coffee",   "native"),
    ("native:mode",        "switch to focus mode",                         "native"),
    ("native:volume",      "louder",                                       "native"),
    ("native:stats",       "how's my machine doing",                       "native"),
    # If openclaw + key are configured, these will route through the
    # bridge. If not, they fall through to the direct LLM.
    ("openclaw-or-llm",    "what's the weather in tokyo",                  None),
    ("llm",                "tell me a one-sentence joke",                  "llm"),
]


def _free_port() -> int:
    """Bind a random port and immediately close it — returns a port
    the OS is unlikely to hand out to another process before we
    re-bind it ourselves. Race-y but good enough for a dev tool."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


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
        start_new_session=True,
    )


def _kill_server(proc: subprocess.Popen) -> None:
    """Tear down the whole process group — `uv run` forks a python
    child and a plain proc.terminate() would orphan it on the port."""
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass


def _wait_ready(client: httpx.Client, timeout_s: float = 15.0) -> bool:
    """Poll /device-display/ until lumi-web is actually serving.
    Return False if it doesn't come up in time."""
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        try:
            r = client.get("/device-display/", timeout=1.0)
            if r.status_code in (200, 503):
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    return False


# ── SSE listener ───────────────────────────────────────────────────────────


@dataclass
class _SSEListener:
    """Background thread that subscribes to /device-display/events and
    records every face-state transition it sees. We don't bother with
    parsing every JSON field — just `state`, since that's the visible
    proof the chat path is driving the display."""

    base_url: str
    states_seen: list[str] = field(default_factory=list)
    stopped: bool = False
    thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopped = True
        if self.thread is not None:
            self.thread.join(timeout=2.0)

    def _run(self) -> None:
        # Fresh client — the main thread's client can't be shared
        # with a long-lived stream without tangling its connection pool.
        client = httpx.Client(base_url=self.base_url, timeout=httpx.Timeout(30.0, read=None))
        try:
            with client.stream("GET", "/device-display/events") as r:
                for line in r.iter_lines():
                    if self.stopped:
                        break
                    if not line.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(line[len("data:"):].strip())
                    except json.JSONDecodeError:
                        continue
                    state = payload.get("state")
                    if state and (not self.states_seen or self.states_seen[-1] != state):
                        self.states_seen.append(state)
        except (httpx.HTTPError, httpx.StreamError):
            pass
        finally:
            client.close()


# ── Per-turn driver ────────────────────────────────────────────────────────


def _drive_turn(
    client: httpx.Client, csrf: str, message: str,
) -> tuple[int, float, str]:
    """Fire one POST /chat/stream, fully consume the SSE body. Returns
    (status, elapsed_ms, last_event_line[:120])."""
    t0 = time.perf_counter()
    try:
        with client.stream(
            "POST", "/chat/stream",
            data={"message": message, "csrf_token": csrf},
            headers={"X-CSRF-Token": csrf},
            timeout=httpx.Timeout(60.0, read=None),
        ) as r:
            last = ""
            for line in r.iter_lines():
                if line:
                    last = line
            return r.status_code, (time.perf_counter() - t0) * 1000, last[:120]
    except (httpx.HTTPError, httpx.StreamError) as exc:
        return -1, (time.perf_counter() - t0) * 1000, f"{type(exc).__name__}: {exc}"[:120]


def _last_audit_entry(client: httpx.Client) -> dict[str, Any]:
    """Read the most recent audit entry off the dashboard — same
    surface the chat-bubble metadata uses, so this matches what the
    UI would show."""
    try:
        r = client.get("/skills/audit-log", params={"n": 1})
        if r.status_code != 200:
            return {}
        # We only need source + skill; the audit log page renders HTML.
        # Easier: read the JSONL directly from the data dir.
    except httpx.HTTPError:
        pass
    return {}


def _last_audit_from_disk(data_dir: Path) -> dict[str, Any]:
    """Tail-read the audit log JSONL directly. Sidesteps the HTML
    audit log viewer."""
    path = data_dir / "audit_log.jsonl"
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8").splitlines()
        for line in reversed(text):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return {}


# ── Main ───────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", default="mock",
                    choices=["mock", "ollama", "hailo"],
                    help="LLM backend the dashboard uses (default: mock — no Ollama needed)")
    ap.add_argument("--port", type=int, default=0,
                    help="Port to bind. 0 = pick a free one (default).")
    ap.add_argument("--data-dir", type=str, default="",
                    help="Existing data dir (with settings, audit log). Default: fresh tmp.")
    args = ap.parse_args()

    port = args.port or _free_port()
    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        cleanup_data_dir = False
    else:
        data_dir = Path(tempfile.mkdtemp(prefix="lumi_demo_"))
        cleanup_data_dir = True

    print(f"▶ spawning lumi-web on :{port}  backend={args.backend}  data_dir={data_dir}")
    proc = _spawn_server(port, data_dir, args.backend)
    base_url = f"http://127.0.0.1:{port}"

    client = httpx.Client(base_url=base_url, timeout=30.0)
    try:
        if not _wait_ready(client):
            print("✗ server failed to come up in 15s — bailing", file=sys.stderr)
            return 2

        # Warm the CSRF cookie + start the SSE listener.
        client.get("/")
        csrf = client.cookies.get("csrf_token", "")

        listener = _SSEListener(base_url=base_url)
        listener.start()
        time.sleep(0.3)  # let the subscriber connect before we start posting

        print(f"\n  {'label':<22}{'status':<8}{'ms':<8}{'audit':<22}match?")
        print(f"  {'-' * 22}{'-' * 8}{'-' * 8}{'-' * 22}{'-' * 8}")

        failures = 0
        for label, msg, expected in DEMO_PROMPTS:
            status, ms, _ = _drive_turn(client, csrf, msg)
            audit = _last_audit_from_disk(data_dir)
            audit_src = audit.get("source", "?")
            audit_skill = audit.get("skill", "?")
            label_audit = f"{audit_src}:{audit_skill}"

            ok = status == 200
            handler_match = (expected is None) or (expected in audit_src)
            tick = "✓" if ok and handler_match else "✗"
            if not (ok and handler_match):
                failures += 1

            print(f"  {label:<22}{status:<8}{ms:<8.0f}{label_audit:<22}{tick}")

        # Let any trailing face-state push land before we stop the listener.
        time.sleep(0.5)
        listener.stop()

        print(f"\n▶ device-display face transitions: {' → '.join(listener.states_seen) or '(none)'}")
        # Heuristic check: we should see at least one think→speak→idle
        # cycle from the chat turns above. If the SSE pipe is broken
        # we'll see "idle" only (or nothing).
        if "think" not in listener.states_seen:
            print("  ⚠ no 'think' state observed — chat-stream → device-display wiring may be broken")
            failures += 1
        if "idle" not in listener.states_seen:
            print("  ⚠ no 'idle' state observed — face never returned to idle after a turn")
            failures += 1

        print(f"\n{'✓ all good' if failures == 0 else f'✗ {failures} regression(s)'}")
        return 0 if failures == 0 else 1
    finally:
        client.close()
        _kill_server(proc)
        if cleanup_data_dir:
            # Best-effort — a leftover tmpdir isn't a real problem.
            import shutil
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
