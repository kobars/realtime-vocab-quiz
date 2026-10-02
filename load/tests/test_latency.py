# AI-ASSISTED: the swarm's percentiles, run summary and its validity rules.

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
    ok = summary(rec, [{"cpu_pct": 40.0, "rss_mb": 50.0}], active_s=60)
    assert ok["valid"]
    assert ok["answer"] == {
        "samples": 3,
        "p50": 20.0,
        "p95": 30.0,
        "p99": 30.0,
        "max": 30.0,
        "missing": 1,
        "timed_out": 0,
        "completion": 0.75,
    }
    assert ok["leaderboard"]["timed_out"] == 2
    assert ok["leaderboard"]["completion"] == round(1 / 3, 4)
    assert ok["msgs_in_per_s"] == 10
    busy = summary(rec, [{"cpu_pct": 40.0, "rss_mb": 1}, {"cpu_pct": 81.0, "rss_mb": 1}], 60)
    assert busy["problems"] == ["a swarm process above 80% CPU"]
    assert "INVALID: a swarm process above 80% CPU" in report(busy)


def test_a_run_without_answer_samples_is_invalid() -> None:
    empty = summary(Recorder(), [{"cpu_pct": 10.0, "rss_mb": 1}], 60)
    assert (empty["valid"], empty["problems"]) == (False, ["no answer samples"])


def test_a_quiz_that_ends_before_the_deadline_makes_the_run_invalid() -> None:
    rec = Recorder(answer_ms=[10.0])
    rec.counts["slots_ended_early"] = 2
    early = summary(rec, [{"cpu_pct": 10.0, "rss_mb": 1}], 60)
    assert early["problems"] == ["2 bot slots stopped at a quiz end before the deadline"]


def test_timed_out_leaderboard_samples_miss_the_slo_of_a_valid_run() -> None:
    rec = Recorder(answer_ms=[10.0] * 10, board_ms=[120.0] * 7)
    rec.counts["board_timeout"] = 3  # 30% of the updates never arrived within the timeout
    missed = summary(rec, [{"cpu_pct": 10.0, "rss_mb": 1}], 60)
    assert missed["valid"]  # the swarm measured correctly; the server missed the target
    assert (missed["slo_met"], missed["slo_within"]) == (False, 0.7)
    assert missed["leaderboard"]["p99"] == 120  # the delivered samples alone look fast
    assert "SLO MISSED" in report(missed)


def test_the_slo_needs_99_percent_of_updates_below_500_ms() -> None:
    on_time = Recorder(answer_ms=[10.0], board_ms=[499.0] * 99 + [500.0])
    met = summary(on_time, [{"cpu_pct": 10.0, "rss_mb": 1}], 60)
    assert (met["slo_met"], met["slo_within"]) == (True, 0.99)
    assert "SLO met" in report(met)
    on_time.counts["board_missing"] = 1  # a dropped socket counts against it too
    assert not summary(on_time, [{"cpu_pct": 10.0, "rss_mb": 1}], 60)["slo_met"]
    unmeasured = summary(Recorder(answer_ms=[10.0]), [{"cpu_pct": 10.0, "rss_mb": 1}], 60)
    assert (unmeasured["slo_met"], unmeasured["slo_within"]) == (False, None)
    assert unmeasured["leaderboard"]["completion"] is None


def test_a_share_just_below_99_percent_misses_the_slo() -> None:
    rec = Recorder(answer_ms=[10.0], board_ms=[100.0] * 989)
    rec.counts["board_missing"] = 10  # 989 of 999 on time: 98.9990%, not 99%
    missed = summary(rec, [{"cpu_pct": 10.0, "rss_mb": 1}], 60)
    assert (missed["slo_met"], missed["slo_within"]) == (False, 0.99)  # rounded for display only


def test_a_total_shown_before_its_answer_result_counts_as_on_time() -> None:
    rec = Recorder(answer_ms=[10.0], board_ms=[100.0] * 98 + [600.0])
    rec.counts["board_first"] = 1  # 99 of 100 updates on time
    assert summary(rec, [{"cpu_pct": 10.0, "rss_mb": 1}], 60)["slo_within"] == 0.99
    assert summary(rec, [{"cpu_pct": 10.0, "rss_mb": 1}], 60)["slo_met"]
    only_first = Recorder(answer_ms=[10.0])
    only_first.counts["board_first"] = 5
    assert summary(only_first, [{"cpu_pct": 10.0, "rss_mb": 1}], 60)["slo_met"]
