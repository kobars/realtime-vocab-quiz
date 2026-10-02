# AI-ASSISTED: the close counter starts each known close code at 0 on import and keeps peer-chosen
# codes to one series.
import subprocess
import sys

SCRAPE = "from quiz.obs import metrics; print(metrics.exposition()[0].decode())"


def test_every_known_close_code_is_scraped_at_0_before_its_first_close() -> None:
    """Only ``obs/metrics.py`` is imported: no gateway or sender module adds a series."""
    out = subprocess.run(
        [sys.executable, "-c", SCRAPE], capture_output=True, text=True, check=True
    ).stdout
    for code in ("1000", "1006", "1008", "1009", "1011", "1012", "1013", "4001", "other"):
        assert f'ws_closes_total{{code="{code}"}} 0.0' in out, code
