# Zod Schema Basics

Zod schemas define the structure and validation rules for your data types. Always define schemas using consistent patterns with proper type inference. Create a dedicated schema file (typically `server/src/schema.ts`) to centralize all type definitions, and use `z.infer<typeof schemaName>` to generate TypeScript types from schemas.

The basic pattern involves creating object schemas with appropriate field validations, then exporting both the schema and its inferred type. For example, `z.string()` for text fields, `z.number()` for numeric values, and `z.coerce.date()` for timestamp fields that need automatic conversion from strings to Date objects. Always validate constraints like `.positive()` for prices or `.int()` for integer-only fields.

Export clean, focused schemas that match your business domain. Create separate schemas for different operations (create vs update inputs) to handle optional fields properly. Keep schemas simple and avoid complex nested validations - prefer composition over deeply nested structures for maintainability.