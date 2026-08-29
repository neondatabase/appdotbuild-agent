# Database Connection Setup

Set up your database connection in `app/database.py` with a standardized pattern that includes engine creation, session management, and table creation utilities. Import all models to ensure they're registered with SQLModel metadata before creating tables. Use environment variables for database URLs with sensible defaults for development.

Implement essential database utilities: `create_tables()` for initial schema creation, `get_session()` for database access, and `reset_db()` for testing scenarios. The engine should use `echo=True` for development to see generated SQL queries. SQLModel handles migrations automatically through `create_all()`, making schema updates straightforward.

Always call `create_tables()` on application startup to ensure the database schema matches your model definitions. Import `desc` and `asc` from sqlmodel when you need to perform ordering operations, as the direct field methods like `field.desc()` don't work properly with SQLModel's query system.
