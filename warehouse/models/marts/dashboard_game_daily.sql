-- One flat table for the dashboard (Looker Studio): every game-day with the game's name and genres, so charts
-- and filters need no joins. Genres are one text field ("Action, Free To Play") because dashboards filter on text.
select
    d.collected_on,
    g.name,
    d.appid,
    array_to_string(g.genres, ', ') as genres,
    g.is_free,
    d.peak_players,
    d.avg_players,
    d.hours_valid,
    d.price_final_usd,
    d.discount_pct,
    d.on_sale,
    d.top_100_rank
from {{ ref('fct_game_daily') }} as d
join {{ ref('dim_games') }} as g using (appid)
