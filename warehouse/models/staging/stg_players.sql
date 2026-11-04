-- One row per game per collected hour. The hour is the run's start, in UTC, which is also the file's name.
-- If one hour was ever collected twice, the later answer wins.
select
    appid,
    player_count,
    suspicious,
    timestamp_trunc(run_started_at, hour) as collected_hour,
    date(run_started_at) as collected_on,
    collected_at,
    source_file
from {{ source('raw', 'players') }}
where true  -- BigQuery wants a WHERE, GROUP BY or HAVING next to QUALIFY
qualify row_number() over (partition by appid, timestamp_trunc(run_started_at, hour) order by collected_at desc) = 1
