-- One flat table for the dashboard (Looker Studio): every game-day with the game's name and genres, so charts
-- and filters need no joins. Genres are one text field ("Action, Free To Play") because dashboards filter on text.
--
-- To compare all games on one chart, each game-day is also measured against the game's own normal level:
-- baseline_avg_players is the game's average daily players on full days without a discount, and
-- players_vs_baseline_pct how far that day was above (+) or below (-) it. A big game and a small one become
-- comparable: "+30%" means the same thing for both. NULL when the game has no full day without a discount yet.
-- discount_band groups discounts for a bar chart; its labels sort in order as text.
with days as (
select
    d.collected_on,
    g.name,
    d.appid,
    array_to_string(g.genres, ', ') as genres,
    g.is_free,
    d.peak_players,
    d.avg_players,
    d.hours_valid,
    d.full_day,
    d.price_final_usd,
    d.discount_pct,
    d.has_store_data,
    d.on_sale,
    d.top_100_rank,
    d.list_source
from {{ ref('fct_game_daily') }} as d
join {{ ref('dim_games') }} as g using (appid)
),

baselines as (
    select
        *,
        avg(if(full_day and on_sale = false, avg_players, null)) over (partition by appid) as baseline_avg_players
    from days
)

select
    *,
    round(100 * safe_divide(avg_players - baseline_avg_players, baseline_avg_players), 1) as players_vs_baseline_pct,
    case
        when on_sale is null then null
        when discount_pct is null or discount_pct = 0 then '0%'
        when discount_pct < 25 then '1-24%'
        when discount_pct < 50 then '25-49%'
        when discount_pct < 75 then '50-74%'
        else '75%+'
    end as discount_band
from baselines
