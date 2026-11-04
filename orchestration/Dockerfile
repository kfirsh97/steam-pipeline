# Airflow, plus a separate Python environment for the pipeline's own code (load.py and dbt).
# Keeping them apart avoids the classic clash between Airflow's and dbt's dependency versions.
FROM apache/airflow:3.3.2-python3.12

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

USER airflow
COPY requirements-warehouse.txt /tmp/requirements-warehouse.txt
RUN python -m venv /opt/airflow/pipeline-venv \
    && /opt/airflow/pipeline-venv/bin/pip install --no-cache-dir -r /tmp/requirements-warehouse.txt
# The repo is mounted from your Mac, owned by your user, not by the container's airflow user.
RUN git config --global --add safe.directory '*'
