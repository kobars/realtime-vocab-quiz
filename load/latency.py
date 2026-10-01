# AI-ASSISTED: the swarm's run summary: percentiles, message rates and the validity rules.
"""Pure code, no I/O; latencies are milliseconds."""

import math
from typing import Any

from player import Recorder

CPU_LIMIT_PCT = 80.0  # a swarm process above this is the bottleneck: the run is invalid


def percentile(sorted_ms: list[float], pct: float) -> float | None:
    """Nearest-rank percentile of an ascending list; ``None`` when it is empty."""
    if not sorted_ms:
        return None
    return sorted_ms[max(0, math.ceil(pct / 100 * len(sorted_ms)) - 1)]


def _latency(samples: list[float], missing: int, timeouts: int) -> dict[str, Any]:
    ordered = [round(ms, 3) for ms in sorted(samples)]
    pct = {f"p{p}": percentile(ordered, p) for p in (50, 95, 99)}
    return {
        "samples": len(ordered),
        **pct,
        "max": ordered[-1] if ordered else None,
        "missing": missing,
        "timed_out": timeouts,
    }


def summary(rec: Recorder, procs: list[dict[str, float]], active_s: float) -> dict[str, Any]:
    """The result document: latencies, message rates over the active ``ramp + duration``,
    counters, the swarm's own CPU, and why the run is invalid, if it is."""
    c, active = rec.counts, max(active_s, 1e-9)
    cpu = max((p["cpu_pct"] for p in procs), default=0.0)
    problems = [f"a swarm process above {CPU_LIMIT_PCT:.0f}% CPU"] if cpu > CPU_LIMIT_PCT else []
    if not rec.answer_ms:
        problems.append("no answer samples")
    return {
        "answer": _latency(rec.answer_ms, c["answer_missing"], c["answer_timeout"]),
        "leaderboard": _latency(rec.board_ms, c["board_missing"], c["board_timeout"]),
        "msgs_in_per_s": round(c["msgs_in"] / active, 1),
        "msgs_out_per_s": round(c["msgs_out"] / active, 1),
        "counts": dict(sorted(c.items())),
        "swarm": {"procs": procs, "cpu_pct_max": cpu},
        "problems": problems,
        "valid": not problems,
    }


def report(result: dict[str, Any]) -> str:
    """Short human-readable lines for the terminal."""
    lines = []
    for name in ("answer", "leaderboard"):
        r = result[name]
        ms = " ".join(
            f"{p}={'-' if r[p] is None else f'{r[p]:.1f}'}" for p in ("p50", "p95", "p99")
        )
        lines.append(
            f"{name:<11} n={r['samples']} {ms} ms missing={r['missing']} timed_out={r['timed_out']}"
        )
    cpu = result["swarm"]["cpu_pct_max"]
    lines.append(f"msg/s in={result['msgs_in_per_s']} out={result['msgs_out_per_s']}")
    verdict = "valid" if result["valid"] else "INVALID: " + "; ".join(result["problems"])
    lines.append(f"swarm cpu max={cpu:.0f}% -> {verdict}")
    return "\n".join(lines)
