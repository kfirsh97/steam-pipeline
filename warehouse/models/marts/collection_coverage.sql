-- One row per finished UTC day since collection began: how much of the day the collector actually captured.
-- A day should have 24 hourly runs and one store run. The scheduler is the usual weak point, so this is measured,
-- not assumed. Days come from a calendar, so a day with no run at all is a row with 0%, not a missing row.
-- valid_coverage_pct also leaves out suspicious zeros, so an hour where many games answered 0 counts less.
with days as (
    select collected_on
    from unnest(generate_date_array(
        (select min(collected_on) from {{ ref('stg_players') }}), date_sub(current_date(), interval 1 day)
    )) as collected_on
),

hours as (
    select
        collected_on,
        count(distinct collected_hour) as hours_collected,
        count(distinct appid) as games_tracked,
        countif(suspicious) as suspicious_counts,
        count(*) as counts,
        count(distinct appid) * count(distinct collected_hour) as counts_possible
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
    d.collected_on,
    coalesce(h.hours_collected, 0) as hours_collected,
    24 as hours_expected,
    round(100 * coalesce(h.hours_collected, 0) / 24, 1) as coverage_pct,
    coalesce(round(100 * h.hours_collected / 24
                   * safe_divide(h.counts - h.suspicious_counts, h.counts_possible), 1), 0) as valid_coverage_pct,
    coalesce(h.games_tracked, 0) as games_tracked,
    coalesce(h.suspicious_counts, 0) as suspicious_counts,
    coalesce(s.store_games, 0) as store_games,
    coalesce(f.player_failures, 0) as player_failures,
    coalesce(f.store_failures, 0) as store_failures
from days as d
left join hours as h using (collected_on)
left join store as s using (collected_on)
left join failures as f using (collected_on)
