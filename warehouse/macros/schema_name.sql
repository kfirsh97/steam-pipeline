{# Datasets are named staging and marts, not steam_staging and steam_marts (dbt's default). #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
