select
    job,
    appid,
    error,
    run_started_at,
    date(run_started_at) as failed_on,
    source_file
from {{ source('raw', 'failures') }}
