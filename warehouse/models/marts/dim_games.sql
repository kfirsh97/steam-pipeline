-- One row per game ever tracked: its latest store details, and when it was in SteamSpy's top 100.
-- The name comes from the store, which is up to date ("Counter-Strike 2"); SteamSpy's can be old.
with latest_store as (
    select *
    from {{ ref('stg_store') }}
    where true
    qualify row_number() over (partition by appid order by collected_on desc) = 1
),

top_list as (
    select
        appid,
        min(collected_on) as first_in_top_100,
        max(collected_on) as last_in_top_100,
        count(*) as days_in_top_100,
        array_agg(steamspy_name ignore nulls order by collected_on desc limit 1)[safe_offset(0)] as steamspy_name,
        array_agg(owners_low ignore nulls order by collected_on desc limit 1)[safe_offset(0)] as owners_low
    from {{ ref('stg_top_games') }}
    group by appid
)

select
    t.appid,
    coalesce(s.name, t.steamspy_name) as name,
    s.type,
    s.is_free,
    s.genres,
    s.release_date,
    s.developer,
    s.publisher,
    t.owners_low,
    t.first_in_top_100,
    t.last_in_top_100,
    t.days_in_top_100
from top_list as t
left join latest_store as s using (appid)
