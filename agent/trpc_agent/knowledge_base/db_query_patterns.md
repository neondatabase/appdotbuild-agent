# Database Query Patterns

Build queries step-by-step using Drizzle's chainable API, starting with `db.select().from(table)` and applying modifications in the correct order. Always use proper operators from 'drizzle-orm': `eq(table.column, value)` for equality, `gte()` for greater-than-or-equal, `desc(table.column)` for descending sort, and `isNull()` for null checks. Never use JavaScript comparison operators directly on table columns.

Apply query modifications in the correct sequence: start with base query, add joins if needed, apply where conditions, then add ordering and pagination. For example: `query = query.where(conditions).orderBy(desc(table.created_at)).limit(10).offset(20)`. This order ensures type inference works correctly and prevents runtime errors.

When building conditional queries, initialize the base query first, then apply filters conditionally using arrays of conditions. Use `and(...conditions)` with the spread operator when combining multiple conditions - never pass an array directly to `and()`. This pattern maintains clean code structure and proper TypeScript inference while supporting dynamic query building based on user input.