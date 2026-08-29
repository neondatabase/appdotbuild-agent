# Query Result Validation and Patterns

Always validate query results before processing them. Check for None values from `.first()` queries and empty results from `.all()` queries. Use explicit patterns: `result = session.exec(select(func.count(Model.id))).first(); total = result if result is not None else 0` rather than relying on `or` operators that can mask important None values.

Convert query results to explicit lists using `list(session.exec(statement).all())` to ensure you're working with predictable data structures. This prevents issues with SQLAlchemy result objects and makes your code more robust when handling collections of database records.

Before using foreign key IDs, ensure they are not None with explicit checks: `if language.id is not None: session_record = StudySession(language_id=language.id, ...)` followed by proper error handling for None cases. This prevents database integrity errors and makes your application more reliable.
