# Drizzle Schema Setup

Define database tables using Drizzle ORM with proper column types and constraints. Use `serial('id').primaryKey()` for auto-incrementing primary keys, `text('name').notNull()` for required string fields, and `numeric('price', { precision: 10, scale: 2 })` for monetary values with specific precision. Always export table schemas to enable proper query building and relationship handling.

Column type selection is crucial for data integrity: use `integer()` for whole numbers, `numeric()` for decimal values requiring precision, `text()` for variable-length strings, and `timestamp().defaultNow()` for audit fields. The `.notNull()` constraint should align exactly with your Zod schema nullability - if Zod has `.nullable()`, omit `.notNull()` from Drizzle.

Always export a tables object containing all your table definitions: `export const tables = { products: productsTable, users: usersTable }`. This pattern enables clean imports in handlers and supports advanced features like relations and joins. Include TypeScript type exports using `$inferSelect` for query results and `$inferInsert` for insert operations to maintain type safety throughout your application.