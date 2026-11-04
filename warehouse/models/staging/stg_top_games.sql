-- One row per game per day in SteamSpy's top 100. owners is a range in the source ("1,000,000 .. 2,000,000");
-- its low end is kept as a number. ccu is SteamSpy's own peak of players at once the day before.
select
    collected_on,
    rank,
    appid,
    name as steamspy_name,
    safe_cast(replace(split(json_value(answer, '$.owners'), ' .. ')[safe_offset(0)], ',', '') as int64) as owners_low,
    safe_cast(json_value(answer, '$.ccu') as int64) as steamspy_peak_players,
    safe_cast(json_value(answer, '$.positive') as int64) as reviews_positive,
    safe_cast(json_value(answer, '$.negative') as int64) as reviews_negative,
    source_file
from {{ source('raw', 'top_games') }}
