# Numeric Type Handling

PostgreSQL's `numeric` type preserves precision by returning string values through Drizzle ORM, while `integer` and `real` types return native JavaScript numbers. Always define Zod schemas with `z.number()` for all numeric database columns, regardless of the underlying type - handle string-to-number conversions in your handlers, not in schemas. Use `z.number().int()` for integer fields to enforce whole number validation.

For decimal/monetary values stored as `numeric` columns, your handlers must convert between strings and numbers: use `toString()` when inserting/updating and `parseFloat()` when selecting data. This conversion is critical because PostgreSQL's numeric type maintains arbitrary precision by avoiding floating-point representation, but JavaScript works with native numbers.

Validation constraints should be applied at the schema level: use `.positive()` for prices, `.nonnegative()` for quantities, and `.int()` for count fields. These validations catch invalid data before it reaches your handlers, providing clear error messages to clients and preventing database constraint violations.