-- One row per game per UTC day: players (from the hourly counts, without the suspicious zeros), the day's price
-- and discount, and its rank in the top 100. This is the table the sale analysis reads.
-- Only finished days: the current UTC day is left out until it is over, so a partial day's low peak is never
-- read as a real one.
-- on_sale is NULL, not false, when there is no store answer for that game and day: unknown is not "full price".
-- full_day: at least 20 usable hourly counts - compare players only on full days (a game that joins or leaves
-- the list mid-day, as 56 did on 2026-11-05, has a partial day).
with players as (
    select
        appid,
        collected_on,
        count(*) as hours_collected,
        countif(not suspicious) as hours_valid,
        max(if(suspicious, null, player_count)) as peak_players,
        round(avg(if(suspicious, null, player_count))) as avg_players
    from {{ ref('stg_players') }}
    where collected_on < current_date()
    group by appid, collected_on
)

select
    p.appid,
    p.collected_on,
    p.hours_collected,
    p.hours_valid,
    p.hours_valid >= 20 as full_day,
    p.peak_players,
    p.avg_players,
    s.price_initial_usd,
    s.price_final_usd,
    s.discount_pct,
    s.source_file is not null as has_store_data,
    if(s.source_file is null, null, coalesce(s.discount_pct > 0, false)) as on_sale,
    s.is_free,
    t.rank as top_100_rank,
    t.list_source
from players as p
left join {{ ref('stg_store') }} as s using (appid, collected_on)
left join {{ ref('stg_top_games') }} as t using (appid, collected_on)
