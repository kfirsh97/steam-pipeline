{# Fails for every row where the column is outside [min_value, max_value]. Empty values pass (not_null checks those). #}
{% test between(model, column_name, min_value, max_value) %}
select {{ column_name }} as value
from {{ model }}
where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endtest %}
