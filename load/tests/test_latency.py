# AI-ASSISTED: the swarm's percentiles, run summary and the CPU validity rule.

from latency import percentile, report, summary
from player import Recorder


def test_percentile_is_nearest_rank() -> None:
    ordered = [float(v) for v in range(1, 101)]
    assert percentile(ordered, 50) == 50
    assert percentile(ordered, 99) == 99
    assert percentile([7.0], 99) == 7
    assert percentile([], 50) is None


def test_the_summary_marks_a_run_with_a_busy_swarm_invalid() -> None:
    rec = Recorder(answer_ms=[10.0, 20.0, 30.0], board_ms=[150.0])
    rec.counts.update(msgs_in=600, board_timeout=2, answer_missing=1)
    ok = summary(rec, [{"cpu_pct": 40.0, "rss_mb": 50.0}], wall_s=60)
    assert ok["valid"]
    assert ok["answer"] == {
        "samples": 3,
        "p50": 20.0,
        "p95": 30.0,
        "p99": 30.0,
        "max": 30.0,
        "missing": 1,
        "timed_out": 0,
    }
    assert ok["leaderboard"]["timed_out"] == 2
    assert ok["msgs_in_per_s"] == 10
    busy = summary(rec, [{"cpu_pct": 40.0, "rss_mb": 1}, {"cpu_pct": 81.0, "rss_mb": 1}], 60)
    assert not busy["valid"]
    assert "INVALID" in report(busy)
