-- One row per game per day in the top-100 list, with its rank. The list is Steam's own most-played chart
-- (source 'steam', with no name or owners); before 2026-11-05, and on days Steam's chart failed, it is SteamSpy's
-- (source 'steamspy'), whose owners range ("1,000,000 .. 2,000,000") is kept by its low end.
-- list_peak_players: the list's own peak of players at once (Steam: peak_in_game; SteamSpy: ccu).
select
    collected_on,
    rank,
    appid,
    coalesce(json_value(answer, '$.source'), 'steamspy') as list_source,
    name as steamspy_name,
    safe_cast(replace(split(json_value(answer, '$.owners'), ' .. ')[safe_offset(0)], ',', '') as int64) as owners_low,
    coalesce(safe_cast(json_value(answer, '$.peak_in_game') as int64),
             safe_cast(json_value(answer, '$.ccu') as int64)) as list_peak_players,
    safe_cast(json_value(answer, '$.positive') as int64) as reviews_positive,
    safe_cast(json_value(answer, '$.negative') as int64) as reviews_negative,
    source_file
from {{ source('raw', 'top_games') }}
