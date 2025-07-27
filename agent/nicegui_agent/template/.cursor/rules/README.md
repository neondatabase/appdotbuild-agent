# NiceGUI Cursor Rules

This directory contains cursor rules for NiceGUI application development with Python, SQLModel, and PostgreSQL.

## Rule Files

### Data Management
- **`data-model-patterns.mdc`** - SQLModel class definitions and schema patterns
- **`database-queries.mdc`** - Query patterns, filtering, and data operations
- **`type-safety.mdc`** - Type hints, Optional handling, and type checking patterns

### Application Architecture
- **`module-organization.mdc`** - Module structure and separation of concerns
- **`state-management.mdc`** - NiceGUI storage patterns (tab, client, user, browser)
- **`event-handlers.mdc`** - Event handling patterns and lambda safety

### UI Development
- **`ui-components.mdc`** - NiceGUI component usage patterns
- **`common-pitfalls.mdc`** - Common mistakes and how to avoid them
- **`none-handling.mdc`** - Handling Optional types and None values in UI

### Testing
- **`testing-patterns.mdc`** - Test strategies, logic vs UI testing approaches

## Template Files

### Reference Examples
- **`base-model.py`** - Complete SQLModel example with relationships and JSON fields
- **`base-module.py`** - Full NiceGUI module with routing, state, and UI components
- **`base-test.py`** - Comprehensive test suite example

## Key Patterns

### Data Layer
- SQLModel for both ORM and validation
- Proper Optional vs nullable field handling
- JSON field support with sa_column
- Type-safe query patterns

### Application Layer
- Modular architecture with create() functions
- Async vs sync page functions based on needs
- Proper state management with storage layers
- Error handling and user notifications

### UI Layer
- Component best practices
- Event handler patterns with None safety
- Two-way data binding
- Dialog and interaction patterns

### Testing
- Logic-focused tests (majority)
- UI smoke tests (minority)
- Database fixtures and cleanup
- Element interaction patterns

## Usage

These rules are automatically applied based on file patterns (globs). Each rule includes:
- Description of the pattern
- File patterns where it applies
- Reference to template files with `@filename`
- Best practices and common pitfalls to avoid

## Development Workflow

1. **Data Modeling** - Define SQLModel classes in `app/models.py`
2. **Module Creation** - Create modules with UI components in `app/`
3. **State Management** - Use appropriate storage layer for data persistence
4. **Testing** - Write logic tests first, add minimal UI tests
5. **Error Handling** - Implement proper None checks and user feedback

## Common Pitfalls to Avoid

1. **ui.date()** - Never pass both positional and keyword 'value' arguments
2. **Lambda functions** - Always capture nullable values safely
3. **SQLModel fields** - Use `# type: ignore[assignment]` for __tablename__
4. **Query results** - Always check for None before using
5. **Date serialization** - Use `.isoformat()` for JSON responses
6. **Boolean comparisons** - Use truthiness, not `== True`
7. **Module registration** - Always call module.create() in startup.py