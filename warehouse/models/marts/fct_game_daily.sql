-- One row per game per UTC day: players (from the hourly counts, without the suspicious zeros), the day's price
-- and discount, and its rank in the top 100. This is the table the sale analysis reads.
with players as (
    select
        appid,
        collected_on,
        count(*) as hours_collected,
        countif(not suspicious) as hours_valid,
        max(if(suspicious, null, player_count)) as peak_players,
        round(avg(if(suspicious, null, player_count))) as avg_players
    from {{ ref('stg_players') }}
    group by appid, collected_on
)

select
    p.appid,
    p.collected_on,
    p.hours_collected,
    p.hours_valid,
    p.peak_players,
    p.avg_players,
    s.price_initial_usd,
    s.price_final_usd,
    s.discount_pct,
    coalesce(s.discount_pct > 0, false) as on_sale,
    s.is_free,
    t.rank as top_100_rank
from players as p
left join {{ ref('stg_store') }} as s using (appid, collected_on)
left join {{ ref('stg_top_games') }} as t using (appid, collected_on)
