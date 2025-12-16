---
name: webapp-creation
description: Build full-stack web applications using Axum (Rust) with HTMX + Alpine.js frontend and Neon (PostgreSQL).
---

You build full-stack stateful web apps from prompts using Axum + HTMX + Alpine.js.

## Architecture

- **Backend**: Axum with SQLx (Rust)
- **Frontend**: Askama templates + HTMX + Alpine.js + PicoCSS
- **Database**: Neon (PostgreSQL)
- **Auth**: Neon Auth (via `neon_auth` schema)
- **Deployment**: Single Docker container 

## Neon Setup

Prerequisites:
- Neon CLI: `npm i -g neonctl`
- jq: `brew install jq`
- sqlx-cli: `cargo install sqlx-cli --features postgres,native-tls`

Required environment variables (in shell, not app):
- `NEON_API_KEY` - Neon API key
- `NEON_PROJECT_ID` - Neon project ID

Setup workflow:
1. Run `./scripts/neon-setup` - creates `{app}-dev` branch, writes `.env`
2. Validate and run migrations: `.claude/skills/webapp-creation/scripts/validate .`
3. Run `./scripts/neon-setup cleanup` to delete branch when done

## Workflow

1. Scaffold: `.claude/skills/webapp-creation/scripts/scaffold <app-name> .`
   - Copies template files to current directory
   - Creates Neon branch (`{app}-dev`)
   - Writes `.env` with DATABASE_URL
2. Define data models in `src/models.rs`
3. Add migration SQL in `migrations/001_init.sql` (use SERIAL for i32, BIGSERIAL for i64)
4. Add route handlers in `src/main.rs` (use Result<T, AppError>, never .expect())
5. Update Askama templates in `templates/` (delete create.html/edit.html if unused)
6. Validate: `.claude/skills/webapp-creation/scripts/validate .`
   - Runs cargo check, clippy, tests, release build
   - Tests Docker build (deployment readiness)
7. Fix any errors before completing
8. Cleanup: `./scripts/neon-setup cleanup` (deletes branch)

## Template Structure

```
template/
├── Cargo.toml              # Dependencies
├── Dockerfile              # Multi-stage Rust build
├── src/
│   ├── main.rs             # Axum server, routes, templates
│   ├── db.rs               # SQLx pool setup (PostgreSQL)
│   └── models.rs           # SQLx FromRow structs
├── templates/
│   ├── base.html           # Base layout with PicoCSS/HTMX/Alpine CDN
│   ├── index.html          # List view
│   ├── edit.html           # Edit form
│   └── create.html         # Create form
├── static/
│   └── styles.css          # Custom overrides (PicoCSS handles base)
├── migrations/
│   └── 001_init.sql        # Database schema
└── scripts/
    └── neon-setup          # Creates dev branch, outputs connection strings
```

## Backend Development

### CRITICAL: Error Handling Rules

**NEVER use `.expect()` or `.unwrap()` in handler functions** - these cause server crashes. Use proper error handling:

1. **All handlers return `Result<T, AppError>`** - errors are logged and return 500 status
2. **Use `?` operator** for all database and template operations
3. **Check `rows_affected()`** for DELETE/UPDATE to return 404 when appropriate

The template includes `AppError` type for proper error handling.

### CRITICAL: Route Path Parameters

**Axum 0.7+ uses `{param}` syntax, NOT `:param`**. Using `:id` causes runtime panic:

```rust
// WRONG - causes panic at startup
.route("/:id/edit", get(edit_form))
.route("/:id", post(update).delete(delete))

// CORRECT - Axum 0.7+ syntax
.route("/{id}/edit", get(edit_form))
.route("/{id}", post(update).delete(delete))
```

This is a runtime error that passes `cargo check` but crashes the app immediately.

### Adding a New Model

1. Define SQLx model in `src/models.rs`:
```rust
#[derive(Debug, Clone, FromRow, Serialize)]
pub struct Task {
    pub id: i32,
    pub title: String,
    pub completed: bool,
}

#[derive(Debug, Deserialize)]
pub struct CreateTask {
    pub title: String,
}

#[derive(Debug, Deserialize)]
pub struct UpdateTask {
    pub title: Option<String>,
    pub completed: Option<bool>,
}
```

2. Add migration in `migrations/001_init.sql`:
```sql
CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT false
);
```

3. Add route handlers in `src/main.rs`:
```rust
async fn list_tasks(State(state): State<AppState>) -> Result<Html<String>, AppError> {
    let tasks = sqlx::query_as::<_, Task>("SELECT * FROM tasks")
        .fetch_all(&state.pool)
        .await?;  // use ? operator, never .expect()
    let template = IndexTemplate { tasks };
    Ok(Html(template.render()?))
}

async fn create_task(
    State(state): State<AppState>,
    Form(input): Form<CreateTask>,
) -> Result<impl IntoResponse, AppError> {
    sqlx::query("INSERT INTO tasks (title) VALUES ($1)")
        .bind(&input.title)
        .execute(&state.pool)
        .await?;  // use ? operator, never .expect()
    Ok(Redirect::to("/"))
}
```

## Frontend Development

### Askama Templates

Templates use Jinja2-like syntax. Update `templates/index.html`:
```html
{% extends "base.html" %}

{% block content %}
<h1>Tasks</h1>
<table>
    <tbody>
        {% for task in tasks %}
        <tr id="task-{{ task.id }}">
            <td>{{ task.title }}</td>
            <td>
                <button
                    hx-delete="/{{ task.id }}"
                    hx-target="#task-{{ task.id }}"
                    hx-swap="outerHTML"
                >Delete</button>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}
```

### HTMX Patterns

- `hx-get`, `hx-post`, `hx-put`, `hx-delete` for HTTP methods
- `hx-target` specifies element to update
- `hx-swap` controls how content is inserted (innerHTML, outerHTML, etc.)
- `hx-confirm` shows confirmation dialog

### Alpine.js Patterns

- `x-data` initializes component state
- `x-model` binds input to state
- `:disabled` for conditional attributes

### PicoCSS

PicoCSS provides classless styling. Semantic HTML elements are styled automatically:
- `<nav>`, `<main>`, `<article>`, `<section>`, `<footer>`
- `<table>`, `<form>`, `<input>`, `<button>`
- Use `class="container"` for centered content with max-width

## Authentication (Neon Auth)

Auth middleware is enabled by default. It extracts `Option<User>` from session cookies by querying the `neon_auth` schema.

### Setup Requirement

Enable Neon Auth in your Neon project console before running the app. The `neon_auth` schema is created automatically.

### Accessing User in Handlers

```rust
use axum::Extension;
use crate::auth::User;

async fn my_handler(Extension(user): Extension<Option<User>>) -> impl IntoResponse {
    match user {
        Some(u) => format!("Hello, {}", u.email),
        None => "Not authenticated".to_string(),
    }
}
```

### User Struct

```rust
pub struct User {
    pub id: String,
    pub email: String,
    pub name: Option<String>,
    pub image: Option<String>,
}
```

### Protected Routes

For routes that require authentication, check the user in the handler:

```rust
async fn protected_route(Extension(user): Extension<Option<User>>) -> impl IntoResponse {
    let user = match user {
        Some(u) => u,
        None => return (StatusCode::UNAUTHORIZED, "Login required").into_response(),
    };
    // ... rest of handler
}
```

## Validation

After writing code, run the validate script (DO NOT run cargo commands directly):
```bash
.claude/skills/webapp-creation/scripts/validate /path/to/app
```

The script runs cargo check, clippy, test, and release build with a shared build cache.

## Constraints

- Rust with strict clippy lints
- Neon (PostgreSQL) for storage - requires `DATABASE_URL`
- All routes at root level (/, /new, /{id}/edit, etc.)
- Must pass validation before completing
