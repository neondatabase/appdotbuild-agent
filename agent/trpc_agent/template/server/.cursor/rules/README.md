# Server-Side Cursor Rules

This directory contains cursor rules for server-side development with tRPC, Drizzle ORM, and PostgreSQL.

## Rule Files

### Core Schema and Database
- **`schema-definition.mdc`** - Zod schema patterns and TypeScript type definitions
- **`database-schema.mdc`** - Drizzle ORM table definitions and database patterns
- **`type-safety.mdc`** - Type alignment between Zod and Drizzle schemas

### Handler Development
- **`handler-patterns.mdc`** - Handler implementation patterns and error handling
- **`database-queries.mdc`** - Query building, conditions, and data transformations
- **`handler-testing.mdc`** - Testing patterns with Bun test framework

### API Configuration
- **`trpc-router.mdc`** - tRPC router setup and procedure definitions

## Template Files

### Reference Examples
- **`base-schema.ts`** - Complete Zod schema example with proper type definitions
- **`base-drizzle-schema.ts`** - Database table definitions with relationships
- **`base-handler.ts`** - Full CRUD handler implementation
- **`base-handler-test.ts`** - Comprehensive test suite example
- **`base-server-index.ts`** - tRPC server configuration

## Key Patterns

### Type Safety
- Zod schemas aligned with Drizzle table definitions
- Proper nullable vs optional field handling
- Numeric type conversions (parseFloat/toString)

### Database Operations
- Conditional query building with proper type safety
- Foreign key validation and constraint handling
- Pagination and sorting implementation

### Error Handling
- Comprehensive try/catch blocks
- Proper error logging with context
- Stack trace preservation

### Testing
- Database setup/teardown patterns
- Isolated test environments
- Real database testing (no mocks)

## Usage

These rules are automatically applied based on file patterns (globs). Each rule includes:
- Description of the pattern
- File patterns where it applies
- Reference to template files with `@filename`
- Best practices and common pitfalls to avoid