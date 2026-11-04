-- One row per UTC day: how much of the day the collector actually captured. A day should have 24 hourly runs
-- (today: the hours so far) and one store run. The scheduler is the usual weak point, so this is measured,
-- not assumed.
with hours as (
    select
        collected_on,
        count(distinct collected_hour) as hours_collected,
        count(distinct appid) as games_tracked,
        countif(suspicious) as suspicious_counts
    from {{ ref('stg_players') }}
    group by collected_on
),

store as (
    select collected_on, count(*) as store_games
    from {{ ref('stg_store') }}
    group by collected_on
),

failures as (
    select failed_on as collected_on, countif(job = 'players') as player_failures, countif(job = 'store') as store_failures
    from {{ ref('stg_failures') }}
    group by failed_on
)

select
    h.collected_on,
    h.hours_collected,
    if(h.collected_on = current_date(), extract(hour from current_timestamp()) + 1, 24) as hours_expected,
    round(100 * h.hours_collected / if(h.collected_on = current_date(), extract(hour from current_timestamp()) + 1, 24), 1)
        as coverage_pct,
    h.games_tracked,
    h.suspicious_counts,
    coalesce(s.store_games, 0) as store_games,
    coalesce(f.player_failures, 0) as player_failures,
    coalesce(f.store_failures, 0) as store_failures
from hours as h
left join store as s using (collected_on)
left join failures as f using (collected_on)
