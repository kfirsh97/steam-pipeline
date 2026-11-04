-- One row per game per day: the store's answer unpacked into columns. Prices are in US dollars (the store
-- answers in cents). A game with no price_overview is either free or not sold in the US store that day.
with daily as (
    select *
    from {{ source('raw', 'store') }}
    where true
    qualify row_number() over (partition by appid, date(run_started_at) order by collected_at desc) = 1
)

select
    appid,
    date(run_started_at) as collected_on,
    json_value(answer, '$.name') as name,
    json_value(answer, '$.type') as type,
    cast(json_value(answer, '$.is_free') as bool) as is_free,
    json_value(answer, '$.price_overview.currency') as currency,
    cast(json_value(answer, '$.price_overview.initial') as int64) / 100 as price_initial_usd,
    cast(json_value(answer, '$.price_overview.final') as int64) / 100 as price_final_usd,
    cast(json_value(answer, '$.price_overview.discount_percent') as int64) as discount_pct,
    safe.parse_date('%b %d, %Y', json_value(answer, '$.release_date.date')) as release_date,
    cast(json_value(answer, '$.release_date.coming_soon') as bool) as coming_soon,
    array(select json_value(g, '$.description') from unnest(json_query_array(answer, '$.genres')) as g) as genres,
    json_value(answer, '$.developers[0]') as developer,
    json_value(answer, '$.publishers[0]') as publisher,
    source_file
from daily
