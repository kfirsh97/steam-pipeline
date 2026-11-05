"""Refresh RowAsk's public demo: export the marts to SQLite and push the file to the rowask repo.

    ROWASK_TOKEN=... python publish_demo.py --project still-sight-513620-v4

Runs as the last Airflow task, after dbt_build, so the demo at rowask.streamlit.app answers from this morning's
warehouse. Streamlit Community Cloud redeploys the app by itself when the repo changes.

Rules:
- The token is a fine-grained GitHub token for the rowask repo only, with Contents read and write only. It is read
  from the environment and handed to git as a request header, never put in a URL or a command line, so it doesn't
  appear in Airflow's logs or in the clone's git config.
- No token set: nothing is pushed, the task says so and succeeds - the pipeline itself doesn't depend on the demo.
- The snapshot is checked before it is pushed (every table there, with rows): a broken export never reaches the
  public demo, which redeploys on every push.
- Nothing changed: no commit. If someone pushed to rowask meanwhile, the clone is reset to their version and the
  file is committed again on top, once.
"""

import argparse
import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = "https://github.com/kfirsh97/rowask.git"
FILE = "data/steam.sqlite"
AUTHOR = ["-c", "user.name=steam-pipeline", "-c", "user.email=kfirsh97@users.noreply.github.com"]


def git_env(token):
    """Environment that gives git the token as an HTTP header for github.com only."""
    env = dict(os.environ)
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {basic}")
    env["GIT_TERMINAL_PROMPT"] = "0"  # never wait for a password
    return env


def git(work, *args, env):
    return subprocess.run(["git", "-C", str(work), *args], env=env, check=True, capture_output=True, text=True)


def fresh_clone(repo, work, env):
    """work becomes an exact copy of the repo's main branch, cloned once and then only updated."""
    work = Path(work)
    if (work / ".git").is_dir():
        git(work, "fetch", "-q", "--depth", "1", "origin", "main", env=env)
        git(work, "reset", "-q", "--hard", "origin/main", env=env)
    else:
        work.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", "main", repo, str(work)],
                       env=env, check=True, capture_output=True, text=True)


def commit_file(work, snapshot, message, env):
    """Copy the snapshot into the clone and commit it. Returns False when the file didn't change."""
    shutil.copyfile(snapshot, Path(work) / FILE)
    git(work, "add", FILE, env=env)
    if not git(work, "status", "--porcelain", FILE, env=env).stdout.strip():
        return False
    git(work, *AUTHOR, "commit", "-q", "-m", message, env=env)
    return True


REQUIRED = {"dashboard_game_daily": 50, "fct_game_daily": 50, "dim_games": 50, "collection_coverage": 1}


def validate(path):
    """Refuse a snapshot the demo can't use: a missing table, or one with fewer rows than REQUIRED."""
    import sqlite3
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table, minimum in REQUIRED.items():
            if table not in tables:
                raise ValueError(f"the snapshot has no {table} table")
            rows = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if rows < minimum:
                raise ValueError(f"the snapshot's {table} has {rows} rows (at least {minimum} expected)")
    finally:
        con.close()


def publish(repo, work, export, token, message="Steam sample: daily snapshot of the warehouse", check=validate):
    """export(path) writes the SQLite file. Returns 'pushed', 'unchanged' or 'no token'."""
    if not token:
        return "no token"
    env = git_env(token)
    fresh_clone(repo, work, env)
    snapshot = Path(work).parent / "steam.sqlite"
    export(snapshot)
    check(snapshot)  # raises: the public demo keeps yesterday's file rather than getting a broken one
    if not commit_file(work, snapshot, message, env):
        return "unchanged"
    try:
        git(work, "push", "-q", "origin", "HEAD:main", env=env)
    except subprocess.CalledProcessError:
        fresh_clone(repo, work, env)  # someone pushed meanwhile: start from their version, once
        if not commit_file(work, snapshot, message, env):
            return "unchanged"
        git(work, "push", "-q", "origin", "HEAD:main", env=env)
    return "pushed"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Push a fresh SQLite snapshot to RowAsk's public demo.")
    parser.add_argument("--project", required=True, help="the Google Cloud project ID")
    parser.add_argument("--work", default="demo/rowask", help="where to keep the rowask clone")
    parser.add_argument("--repo", default=REPO)
    args = parser.parse_args(argv)

    def export(path):
        from google.cloud import bigquery
        import export_sqlite
        counts = export_sqlite.export(bigquery.Client(project=args.project, location=export_sqlite.LOCATION),
                                      args.project, path)
        for table, count in counts.items():
            print(f"{table}: {count} rows")

    try:
        result = publish(args.repo, args.work, export, os.environ.get("ROWASK_TOKEN", "").strip())
    except subprocess.CalledProcessError as error:
        print(f"git failed: {error.stderr.strip()}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"publish failed: {error}", file=sys.stderr)
        return 1
    print({"pushed": f"pushed a new {FILE} to {args.repo}",
           "unchanged": "the snapshot didn't change: nothing to push",
           "no token": "WARNING: ROWASK_TOKEN is not set in orchestration/.env - the demo was not refreshed"}[result])
    return 0


if __name__ == "__main__":
    sys.exit(main())
