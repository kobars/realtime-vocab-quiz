# AI-ASSISTED: samples the API nodes' CPU and memory with docker stats during a load run.
"""Sample ``docker stats`` of the API nodes during a load run and write each node's mean and peak
CPU (percent of one core) and its memory before the run and at its peak to ``load/results/``.

Start it on the host together with ``make load``: it takes the idle sample at once, waits
``--ramp`` seconds, then samples every ``--every`` seconds for ``--duration`` seconds, the swarm's
answering window. Memory is what docker stats reports: the container's usage without page cache.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from statistics import fmean
from typing import Any

from bots import save

CONTAINERS = "elsaquiz-api-1-1,elsaquiz-api-2-1"
UNITS = {"B": 2**-20, "KiB": 2**-10, "MiB": 1.0, "GiB": 2**10, "kB": 1e3 / 2**20, "MB": 1e6 / 2**20}
UNITS["GB"] = 1e9 / 2**20

Sample = dict[str, tuple[float, float]]  # container -> (CPU %, memory MiB)


def mib(text: str) -> float:
    """A docker stats size such as ``123.4MiB`` in MiB."""
    size = re.fullmatch(r"([\d.]+)\s*([A-Za-z]+)", text.strip())
    if size is None or size[2] not in UNITS:
        msg = f"not a docker stats size: {text!r}"
        raise ValueError(msg)
    return float(size[1]) * UNITS[size[2]]


def parse(out: str) -> Sample:
    """The JSON lines of ``docker stats --format '{{json .}}'``."""
    rows = (json.loads(row) for row in out.splitlines() if row.strip())
    return {
        r["Name"]: (float(r["CPUPerc"].rstrip("%")), mib(r["MemUsage"].split("/")[0])) for r in rows
    }


def sample(containers: list[str]) -> Sample:
    cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}", *containers]
    return parse(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)  # noqa: S603


def summarize(idle: Sample, samples: list[Sample]) -> dict[str, Any]:
    """Per node: mean and peak CPU and peak memory over the samples, and the idle memory."""
    nodes = {}
    for name, (_, idle_mib) in idle.items():
        cpu = [s[name][0] for s in samples if name in s]
        mem = [s[name][1] for s in samples if name in s]
        nodes[name] = {
            "cpu_pct_mean": round(fmean(cpu), 1) if cpu else None,
            "cpu_pct_max": max(cpu, default=None),
            "mem_mib_idle": round(idle_mib, 1),
            "mem_mib_max": round(max(mem), 1) if mem else None,
        }
    return {"samples": len(samples), "nodes": nodes}


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    add = cli.add_argument
    add("--containers", default=CONTAINERS, help="comma-separated API node containers")
    add("--ramp", type=float, default=10, help="seconds to wait after the idle sample")
    add("--duration", type=float, default=60, help="seconds to sample for")
    add("--every", type=float, default=5, help="seconds between samples")
    add("--label", default="run", help="name part of the result file, before -nodes")
    a = cli.parse_args(argv)
    containers = [c.strip() for c in a.containers.split(",") if c.strip()]
    idle = sample(containers)
    time.sleep(a.ramp)
    samples, end = [], time.monotonic() + a.duration
    while (now := time.monotonic()) < end:
        samples.append(sample(containers))
        time.sleep(max(0.0, min(a.every - (time.monotonic() - now), end - time.monotonic())))
    result = {"options": vars(a), **summarize(idle, samples)}
    print(json.dumps(result["nodes"], indent=2))
    print(f"written: {save(result, f'{a.label}-nodes')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
