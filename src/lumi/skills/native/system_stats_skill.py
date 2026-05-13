"""Native system stats skill — CPU, RAM, disk usage. No network required."""

from __future__ import annotations

import re

from ..base import NativeSkill, SkillResult

_TRIGGERS = re.compile(
    r"\b(system stats?|how(?:'s| is)(?: my)? (?:machine|computer|cpu|ram|memory|disk)|"
    r"cpu usage|memory usage|disk space|resource)\b",
    re.IGNORECASE,
)


def _get_stats() -> dict[str, str]:
    try:
        import psutil  # noqa: PLC0415

        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "cpu": f"{cpu:.0f}%",
            "ram": f"{mem.percent:.0f}% ({mem.used // (1024**3):.1f}/{mem.total // (1024**3):.1f} GB)",
            "disk": f"{disk.percent:.0f}% ({disk.used // (1024**3):.1f}/{disk.total // (1024**3):.1f} GB)",
        }
    except ImportError:
        return _get_stats_fallback()


def _get_stats_fallback() -> dict[str, str]:
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    stats: dict[str, str] = {}
    if sys.platform == "darwin":
        try:
            r = subprocess.run(
                ["top", "-l", "1", "-n", "0"],
                capture_output=True, text=True, timeout=5,
            )
            for line in r.stdout.splitlines():
                if "CPU usage" in line:
                    stats["cpu"] = line.strip()
                    break
        except Exception:
            stats["cpu"] = "unknown"
    else:
        stats["cpu"] = "Install psutil for stats: uv pip install psutil"
    return stats


class SystemStatsSkill(NativeSkill):
    def matches(self, transcript: str) -> bool:
        return bool(_TRIGGERS.search(transcript))

    def execute(self, transcript: str) -> SkillResult:
        stats = _get_stats()
        if "cpu" in stats and "ram" in stats:
            return SkillResult(
                text=f"CPU at {stats['cpu']}, RAM at {stats['ram']}, disk at {stats['disk']}."
            )
        if "cpu" in stats:
            return SkillResult(text=stats["cpu"])
        return SkillResult(text="Couldn't read system stats.")
