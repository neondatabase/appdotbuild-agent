---
name: rust-webapp-creation
description: Build web applications using Axum (Rust) with HTMX + Alpine.js frontend and Neon (serverless PostgreSQL).
---

Build full-stack stateful web apps using Axum + HTMX + Alpine.js + Neon (PostgreSQL).

## Overview

- **Backend**: Axum with SQLx (Rust)
- **Frontend**: Askama templates + HTMX + Alpine.js + PicoCSS
- **Database**: Neon (PostgreSQL)
- **Deployment**: Single Docker container

## Workflow

### Phase 1: Setup

Prerequisites (install once):
```bash
npm i -g neonctl
brew install jq
cargo install sqlx-cli --features postgres,native-tls
```

Required env vars (in shell):
- `NEON_API_KEY` - Neon API key
- `NEON_PROJECT_ID` - Neon project ID

Scaffold app:
```bash
NEON_BRANCH_TTL=2h .claude/skills/webapp-creation/scripts/scaffold <app-name> .
```

This creates app files and a Neon branch (`{app}-dev`) with 2h expiration. Branch auto-expires, no cleanup needed.

### Phase 2: Data Modeling

1. Define models in `src/models.rs`
2. Write migration SQL in `migrations/001_init.sql`
3. Use `SERIAL` for i32, `BIGSERIAL` for i64

Reference: [Models](./reference/models.md) - SQLx patterns, struct definitions, type mapping

### Phase 3: Backend Implementation

1. Add route handlers in `src/main.rs`
2. All handlers return `Result<T, AppError>` - use `?` operator
3. **NEVER** use `.expect()` or `.unwrap()` - causes server crashes
4. Route params use `{id}` syntax (NOT `:id`)

Reference: [Handlers](./reference/handlers.md) - CRUD patterns, router setup, transactions

### Phase 4: Frontend

1. Update Askama templates in `templates/`
2. Delete unused template files (create.html, edit.html if not needed)
3. Use HTMX for interactivity, Alpine.js for state

Reference: [Templates](./reference/templates.md) - Askama, HTMX, Alpine patterns
Reference: [Design](./reference/design.md) - CSS components, layout patterns

### Phase 5: Validation & Deploy

Validate (runs cargo check, clippy, tests, release build):
```bash
.claude/skills/webapp-creation/scripts/validate .
```

Fix all errors before completing. Branch auto-expires after TTL.

## Template Structure

```
├── Cargo.toml              # Dependencies
├── Dockerfile              # Multi-stage Rust build
├── src/
│   ├── main.rs             # Axum server, routes, templates
│   ├── db.rs               # SQLx pool setup
│   └── models.rs           # Data structs
├── templates/
│   ├── base.html           # Base layout (PicoCSS/HTMX/Alpine CDN)
│   ├── index.html          # List view
│   ├── edit.html           # Edit form
│   └── create.html         # Create form
├── static/
│   └── styles.css          # Custom CSS overrides
└── migrations/
    └── 001_init.sql        # Database schema
```

## Critical Rules

1. **NEVER `.expect()` or `.unwrap()`** in handlers - use `?` operator
2. **Route params: `{id}` not `:id`** - wrong syntax compiles but panics at runtime
3. **All handlers return `Result<T, AppError>`**
4. **Check `rows_affected()`** for DELETE/UPDATE to return 404
5. **Use compile-time SQLx macros** (`query!`, `query_as!`)

Full list: [Pitfalls](./reference/pitfalls.md)

## Constraints

- Neon (PostgreSQL) required - needs `DATABASE_URL`
- All routes at root level (/, /new, /{id}/edit)
- Strict clippy lints - must pass validation
- Must pass validation before completing
