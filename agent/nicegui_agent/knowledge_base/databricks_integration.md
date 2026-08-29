# Databricks Integration Patterns

Always check real table structure and data in Databricks before implementing models. Use the `DatabricksModel` base class with proper catalog, schema, and table class variables: `__catalog__ = "samples"`, `__schema__ = "accuweather"`, `__table__ = "forecast_daily_calendar_imperial"`. The `table_name()` method constructs the full table reference.

Implement the `fetch()` method for each DatabricksModel to execute SQL queries and return model instances. Use `execute_databricks_query(query)` to run SQL and convert results with `[cls(**row) for row in raw_results]`. Use parameterized queries with proper f-string formatting for dynamic values like date ranges.

Follow best practices: validate query results before processing, use descriptive error messages, log query execution for monitoring, and consider performance with appropriate limits. Use reasonable default parameter values in fetch methods to prevent long-running queries. For quick results, consider fetching aggregated data and storing it in PostgreSQL for faster subsequent access.
