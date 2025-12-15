---
name: webapp-creation
description: Build full-stack web applications using Axum (Rust) with HTMX + Alpine.js frontend and Neon (PostgreSQL).
---

You build full-stack web apps from prompts using Axum + HTMX + Alpine.js.

## Architecture

- **Backend**: Axum with SQLx (Rust)
- **Frontend**: Askama templates + HTMX + Alpine.js + PicoCSS
- **Database**: Neon (PostgreSQL)
- **Deployment**: Single Docker container

## Neon Setup

Prerequisites:
- Neon CLI: `npm i -g neonctl`
- jq: `brew install jq`

Required environment variables:
- `NEON_API_KEY` - Neon API key (for branch management)
- `NEON_PROJECT_ID` - Neon project ID

Optional environment variables:
- `NEON_ROLE_NAME` - database role (defaults to `neondb_owner`)
- `NEON_PROD_BRANCH` - production branch name (auto-detected)
- `NEON_DEV_BRANCH` - development branch name (defaults to `dev`)

Setup workflow:
1. Create a Neon project at https://neon.tech
2. Run `./scripts/neon-setup <app-name>` to create app branch (e.g., `myapp-dev`)
3. Set `DATABASE_URL` to the dev branch connection string
4. Run `./scripts/neon-setup <app-name> cleanup` to delete branch when done

## Workflow

1. Read template files from this skill's `template/` directory
2. Copy ALL template files to the output directory
3. Define data models in `src/models.rs`
4. Add migration SQL in `migrations/001_init.sql`
5. Add route handlers in `src/main.rs`
6. Update Askama templates in `templates/`
7. Run validation: execute `scripts/validate` with the app path
8. Fix any errors before completing

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
async fn list_tasks(State(state): State<AppState>) -> Html<String> {
    let tasks = sqlx::query_as::<_, Task>("SELECT * FROM tasks")
        .fetch_all(&state.pool)
        .await
        .expect("query failed");
    let template = IndexTemplate { tasks };
    Html(template.render().expect("render failed"))
}

async fn create_task(
    State(state): State<AppState>,
    Form(input): Form<CreateTask>,
) -> impl IntoResponse {
    sqlx::query("INSERT INTO tasks (title) VALUES ($1)")
        .bind(&input.title)
        .execute(&state.pool)
        .await
        .expect("insert failed");
    Redirect::to("/")
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

## Validation

After writing code, run the validate script:
```bash
.claude/skills/webapp-creation/scripts/validate /path/to/app
```

This runs:
- `cargo check` - compilation check
- `cargo clippy -- -D warnings` - lints (warnings are errors)
- `cargo test` - unit tests
- `cargo build --release` - release build

## Constraints

- Rust with strict clippy lints
- Neon (PostgreSQL) for storage - requires `DATABASE_URL`
- All routes at root level (/, /new, /{id}/edit, etc.)
- Must pass validation before completing
