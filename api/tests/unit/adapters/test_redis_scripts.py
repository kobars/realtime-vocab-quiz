# AI-ASSISTED: the script loader lists only the .lua files of its folder as scripts.
from pathlib import Path

from quiz.adapters.redis.scripts import SCRIPTS, script_names


def test_only_lua_files_beside_lib_are_scripts(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    for name in ("join.lua", "end_quiz.lua", ".DS_Store", "join.lua~", "notes.txt"):
        (tmp_path / name).write_text("")
    assert script_names(tmp_path) == ("end_quiz", "join")


def test_the_packaged_scripts_are_listed() -> None:
    assert "publish_leaderboard" in SCRIPTS
    assert all(not name.startswith(".") for name in SCRIPTS)
