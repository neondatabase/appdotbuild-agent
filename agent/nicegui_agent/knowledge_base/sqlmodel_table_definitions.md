# SQLModel Table Definitions

Organize all SQLModel classes in `app/models.py` with clear separation between persistent models (`table=True`) and non-persistent schemas (`table=False`). Persistent models are stored in the database, while schemas are used for validation, forms, and API requests/responses. Always add `# type: ignore[assignment]` to `__tablename__` declarations to avoid type checker errors.

Define proper field constraints using `Field()` with appropriate validation rules, foreign key relationships, and default values. Use `datetime.utcnow` as `default_factory` for timestamps, and `Decimal('0')` for decimal fields. For JSON/List/Dict fields in database models, use `sa_column=Column(JSON)` to ensure proper PostgreSQL storage.

Implement relationships using `Relationship()` for foreign key connections, but only in table models. Always validate query results before processing: check for None values, convert results to explicit lists with `list(session.exec(statement).all())`, and use proper sorting with `desc(Model.field)` imported from sqlmodel rather than `Model.field.desc()`.
