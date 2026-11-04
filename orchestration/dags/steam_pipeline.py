"""Step 4: the daily pipeline run, orchestrated by Airflow.

Every morning at 04:30 UTC (06:30 Israel in winter), for the UTC day that just ended:

    pull_raw_files  ->  check_day_collected  ->  load_raw  ->  dbt_build

- pull_raw_files       brings the data branch clone up to date with what GitHub Actions collected
- check_day_collected  makes sure the day's hourly files and store file arrived; if not, it fails and is
                       retried (twice, 20 minutes apart), so a late collector doesn't load an empty day
- load_raw             load.py: rebuilds the raw tables in BigQuery from all the files
- dbt_build            builds the staging and mart models and runs the data tests

catchup=True: if the computer was off for three days, Airflow creates one run for each missed day when it
comes back, oldest first, one at a time - each one checks its own day. The load and dbt build rebuild every
table from all the files, so after a catch-up the warehouse is complete, whichever run finished last.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, task
from airflow.timetables.interval import CronDataIntervalTimetable

sys.path.insert(0, os.path.dirname(__file__))  # day_check.py sits next to this file
from day_check import check_day  # noqa: E402

HOME = os.environ.get("PIPELINE_HOME", "/opt/steam-pipeline")
BIN = os.environ.get("PIPELINE_PYTHON", "/opt/airflow/pipeline-venv/bin")
DATA_BRANCH = "https://github.com/kfirsh97/steam-pipeline.git"


@dag(
    dag_id="steam_pipeline",
    # An interval timetable: each run covers the 24 hours before it, so its data_interval_start is the UTC day
    # being checked. (Airflow 3's plain cron string would start and end the interval at the run time.)
    schedule=CronDataIntervalTimetable("30 4 * * *", timezone="UTC"),
    start_date=datetime(2026, 11, 4, tzinfo=timezone.utc),
    catchup=True,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=20)},
    tags=["steam"],
    doc_md=__doc__,
)
def steam_pipeline():
    pull = BashOperator(
        task_id="pull_raw_files",
        bash_command=(
            f"cd {HOME} && "
            f"if [ -d store/.git ]; then git -C store pull --ff-only -q; "
            f"else git clone -q --branch data --single-branch {DATA_BRANCH} store; fi"
        ),
        execution_timeout=timedelta(minutes=5),
    )

    @task(execution_timeout=timedelta(minutes=2))
    def check_day_collected(data_interval_start=None):
        # A run started by hand may have no data interval: then it checks yesterday (UTC).
        start = data_interval_start or datetime.now(timezone.utc) - timedelta(days=1)
        result = check_day(f"{HOME}/store", start.strftime("%Y-%m-%d"))
        for warning in result["warnings"]:
            print(f"WARNING: {warning}")
        print(f"{result['day']}: {result['hours']} hours, store file present")
        return result

    load = BashOperator(
        task_id="load_raw",
        bash_command=f"cd {HOME} && {BIN}/python load.py --data store --project $GCP_PROJECT",
        execution_timeout=timedelta(minutes=15),
    )

    build = BashOperator(
        task_id="dbt_build",
        bash_command=f"cd {HOME}/warehouse && {BIN}/dbt build --profiles-dir .",
        execution_timeout=timedelta(minutes=20),
    )

    pull >> check_day_collected() >> load >> build


steam_pipeline()
