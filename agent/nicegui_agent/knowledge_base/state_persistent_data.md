# Persistent Data Management

Use PostgreSQL database with SQLModel ORM for persistent data that needs to survive server restarts and be shared across users. This includes user accounts, application data, settings, and any information that forms the core business logic of your application.

Structure your persistent data with proper relationships, constraints, and validation using SQLModel classes with `table=True`. Always call `create_tables()` on application startup to ensure your database schema matches your model definitions. Use proper field types, foreign keys, and indexes for optimal performance.

Avoid storing critical business data in NiceGUI's storage mechanisms (`app.storage.*`) as these are intended for temporary data like UI state, user preferences, and session information. Keep your persistent data layer separate from your UI state to maintain proper architecture separation.
