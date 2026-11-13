-- The sale analysis: every sale that starts while the game is tracked, with the days around its start.
-- One row per sale per day, from 7 days before the first discounted day to 14 days after it. The chart puts
-- days_from_sale_start on the x axis (negative = before, 0 = first sale day) and averages
-- players_vs_baseline_pct over all sales, so many games of different sizes show one before/during/after shape.
--
-- A sale "starts" on a discounted day whose previous day was collected and not discounted. Sales already running
-- on the first collected day are left out: their start wasn't seen.
with days as (
    select appid, name, collected_on, on_sale, discount_pct, avg_players, players_vs_baseline_pct, full_day
    from {{ ref('dashboard_game_daily') }}
),

flagged as (
    select
        *,
        lag(on_sale) over (partition by appid order by collected_on) as previous_on_sale,
        lag(collected_on) over (partition by appid order by collected_on) as previous_day
    from days
),

starts as (
    select appid, collected_on as sale_start, discount_pct as sale_discount_pct
    from flagged
    where on_sale and previous_on_sale = false and date_diff(collected_on, previous_day, day) = 1
)

select
    s.appid,
    d.name,
    s.sale_start,
    s.sale_discount_pct,
    date_diff(d.collected_on, s.sale_start, day) as days_from_sale_start,
    d.collected_on,
    d.on_sale,
    d.discount_pct,
    d.avg_players,
    d.players_vs_baseline_pct,
    d.full_day
from starts as s
join days as d
    on d.appid = s.appid
    and d.collected_on between date_sub(s.sale_start, interval 7 day) and date_add(s.sale_start, interval 14 day)
