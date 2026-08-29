# Schema Type Alignment

Critical alignment between Zod and Drizzle types is essential for type safety. Drizzle fields with `.notNull()` should NOT have `.nullable()` in Zod, while Drizzle fields without `.notNull()` MUST have `.nullable()` in Zod schemas. Never use `.nullish()` in Zod - always be explicit with `.nullable()` or `.optional()` based on your database schema.

For numeric types, remember that Drizzle `numeric()` columns return STRING values from PostgreSQL to preserve precision, while `real()` and `integer()` return native numbers. Always define Zod schemas with `z.number()` for ALL numeric column types regardless of the underlying database representation - handle conversions in your handlers, not in schemas.

Date handling requires special attention: use `z.coerce.date()` for Drizzle `timestamp()` fields to automatically convert string timestamps to Date objects. For enum fields, create matching Zod enums with `z.enum([...])` and never accept raw strings - always validate against the defined enum values to prevent runtime errors.