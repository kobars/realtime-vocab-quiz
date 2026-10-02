# AI-ASSISTED: the API nodes' CPU and memory summary from docker stats lines.
import json

import pytest
from node_stats import mib, parse, summarize


def line(name: str, cpu: str, mem: str) -> str:
    return json.dumps({"Name": name, "CPUPerc": cpu, "MemUsage": f"{mem} / 7.75GiB", "PIDs": "5"})


@pytest.mark.parametrize(
    ("text", "expected"),
    [("512KiB", 0.5), ("123.5MiB", 123.5), ("1.5GiB", 1536.0), ("0B", 0.0), ("1MB", 0.954)],
)
def test_memory_reads_in_mib(text: str, expected: float) -> None:
    assert mib(text) == pytest.approx(expected, abs=0.001)


@pytest.mark.parametrize("text", ["", "12", "3 PiB"])
def test_an_unknown_size_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="docker stats size"):
        mib(text)


def test_each_line_gives_a_nodes_cpu_and_memory() -> None:
    out = "\n".join([line("api-1", "87.25%", "120MiB"), line("api-2", "101.50%", "1.25GiB"), ""])
    assert parse(out) == {"api-1": (87.25, 120.0), "api-2": (101.5, 1280.0)}


def test_the_summary_has_the_mean_and_peak_per_node_and_the_idle_memory() -> None:
    idle = {"api-1": (0.5, 60.0)}
    samples = [{"api-1": (80.0, 100.0)}, {"api-1": (90.0, 140.0)}, {}]  # a missed sample
    assert summarize(idle, samples) == {
        "samples": 3,
        "nodes": {
            "api-1": {
                "cpu_pct_mean": 85.0,
                "cpu_pct_max": 90.0,
                "mem_mib_idle": 60.0,
                "mem_mib_max": 140.0,
            }
        },
    }


def test_a_node_with_no_sample_has_no_numbers() -> None:
    node = summarize({"api-1": (0.0, 60.0)}, [])["nodes"]["api-1"]
    assert node == {
        "cpu_pct_mean": None,
        "cpu_pct_max": None,
        "mem_mib_idle": 60.0,
        "mem_mib_max": None,
    }
