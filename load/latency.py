# AI-ASSISTED: the swarm's run summary: percentiles, message rates, the validity rules, the SLO.
"""Pure code, no I/O; latencies are milliseconds."""

import math
from typing import Any

from player import Recorder

CPU_LIMIT_PCT = 80.0  # a swarm process above this is the bottleneck: the run is invalid
SLO_MS, SLO_SHARE = 500.0, 0.99  # C5: 99% of leaderboard updates delivered below 500 ms


def percentile(sorted_ms: list[float], pct: float) -> float | None:
    """Nearest-rank percentile of an ascending list; ``None`` when it is empty."""
    if not sorted_ms:
        return None
    return sorted_ms[max(0, math.ceil(pct / 100 * len(sorted_ms)) - 1)]


def _share(part: int, attempts: int) -> float | None:
    """``part`` over ``attempts``, unrounded so a threshold compares the exact share."""
    return part / attempts if attempts else None


def _rounded(share: float | None) -> float | None:
    return None if share is None else round(share, 4)


def _latency(samples: list[float], missing: int, timeouts: int) -> dict[str, Any]:
    ordered = [round(ms, 3) for ms in sorted(samples)]
    pct = {f"p{p}": percentile(ordered, p) for p in (50, 95, 99)}
    return {
        "samples": len(ordered),
        **pct,
        "max": ordered[-1] if ordered else None,
        "missing": missing,
        "timed_out": timeouts,
        # a missing or timed-out sample is a failed attempt
        "completion": _rounded(_share(len(ordered), len(ordered) + missing + timeouts)),
    }


def summary(rec: Recorder, procs: list[dict[str, float]], active_s: float) -> dict[str, Any]:
    """The result document: latencies, message rates over the active ``ramp + duration``,
    counters, the swarm's own CPU, why the run is invalid, if it is, and whether the server met
    the SLO. ``valid`` judges the measurement, ``slo_met`` the server."""
    c, active = rec.counts, max(active_s, 1e-9)
    cpu = max((p["cpu_pct"] for p in procs), default=0.0)
    problems = [f"a swarm process above {CPU_LIMIT_PCT:.0f}% CPU"] if cpu > CPU_LIMIT_PCT else []
    if not rec.answer_ms:
        problems.append("no answer samples")
    if early := c["slots_ended_early"]:
        problems.append(f"{early} bot slots stopped at a quiz end before the deadline")
    board = (rec.board_ms, c["board_missing"], c["board_timeout"])
    # A total a frame showed before its answer_result was delivered as the interval began: on time.
    # An answer whose reply was lost or late opened no wait, so nothing proves its update was on
    # time: a miss, even though a wrong answer among them would have changed nothing.
    first, unproven = c["board_first"], c["answer_missing"] + c["answer_timeout"]
    on_time = sum(ms < SLO_MS for ms in rec.board_ms) + first
    within = _share(on_time, len(rec.board_ms) + sum(board[1:]) + first + unproven)
    if within is None:
        problems.append("no leaderboard samples")
    return {
        "answer": _latency(rec.answer_ms, c["answer_missing"], c["answer_timeout"]),
        "leaderboard": _latency(*board),
        "msgs_in_per_s": round(c["msgs_in"] / active, 1),
        "msgs_out_per_s": round(c["msgs_out"] / active, 1),
        "counts": dict(sorted(c.items())),
        "swarm": {"procs": procs, "cpu_pct_max": cpu},
        "problems": problems,
        "valid": not problems,
        "slo_within": _rounded(within),
        "slo_met": within is not None and within >= SLO_SHARE,
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
    within = "-" if result["slo_within"] is None else f"{result['slo_within']:.2%}"
    slo = "SLO met" if result["slo_met"] else "SLO MISSED"
    lines.append(f"leaderboard below {SLO_MS:.0f} ms: {within} of updates -> {slo}")
    return "\n".join(lines)
