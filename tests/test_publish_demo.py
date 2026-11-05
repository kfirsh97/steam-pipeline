import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_demo  # noqa: E402

OK = lambda path: None  # the fake snapshots below are not real SQLite files


def run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def remote(tmp_path):
    """A bare repo standing in for rowask on GitHub, with one commit on main."""
    bare = tmp_path / "rowask.git"
    run("git", "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    run("git", "clone", "-q", str(bare), str(seed))
    (seed / "data").mkdir()
    (seed / "data" / "steam.sqlite").write_bytes(b"old")
    run("git", "add", "-A", cwd=seed)
    run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed", cwd=seed)
    run("git", "push", "-q", "origin", "HEAD:main", cwd=seed)
    return bare


def file_on_main(bare):
    return run("git", "--git-dir", str(bare), "show", "main:data/steam.sqlite")


def test_pushes_a_new_snapshot_and_skips_an_unchanged_one(tmp_path):
    bare = remote(tmp_path)
    work = tmp_path / "work" / "rowask"
    write = lambda content: (lambda path: Path(path).write_bytes(content))
    assert publish_demo.publish(str(bare), work, write(b"day 1"), "tok", check=OK) == "pushed"
    assert file_on_main(bare) == "day 1"
    assert publish_demo.publish(str(bare), work, write(b"day 1"), "tok", check=OK) == "unchanged"
    assert publish_demo.publish(str(bare), work, write(b"day 2"), "tok", check=OK) == "pushed"
    assert file_on_main(bare) == "day 2"


def test_no_token_pushes_nothing(tmp_path):
    bare = remote(tmp_path)
    assert publish_demo.publish(str(bare), tmp_path / "w" / "r", lambda p: Path(p).write_bytes(b"x"), "") == "no token"
    assert file_on_main(bare) == "old"


def test_the_token_stays_out_of_the_clone_config(tmp_path):
    bare = remote(tmp_path)
    work = tmp_path / "work" / "rowask"
    publish_demo.publish(str(bare), work, lambda p: Path(p).write_bytes(b"x"), "secret-token", check=OK)
    assert "secret" not in (work / ".git" / "config").read_text()
    header = publish_demo.git_env("secret-token")["GIT_CONFIG_VALUE_0"]
    assert header.startswith("AUTHORIZATION: basic ") and "secret-token" not in header


def test_a_broken_snapshot_is_not_pushed(tmp_path):
    import sqlite3
    bare = remote(tmp_path)

    def export(path):
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE dim_games (appid INTEGER)")
        con.commit()
        con.close()
    with pytest.raises(ValueError, match="no dashboard_game_daily"):
        publish_demo.publish(str(bare), tmp_path / "w" / "r", export, "tok")
    assert file_on_main(bare) == "old"
