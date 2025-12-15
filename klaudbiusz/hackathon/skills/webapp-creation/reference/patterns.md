# Full-Stack Patterns: Axum + HTMX + Alpine.js

## Backend (Axum + SQLx)

### Model Definition

Use SQLx FromRow derive:

```rust
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

#[derive(Debug, Clone, FromRow, Serialize)]
pub struct User {
    pub id: i32,
    pub email: String,
    pub name: String,
    pub is_active: bool,
}

#[derive(Debug, Clone, FromRow, Serialize)]
pub struct Task {
    pub id: i32,
    pub title: String,
    pub completed: bool,
    pub owner_id: i32,
}

#[derive(Debug, Deserialize)]
pub struct CreateTask {
    pub title: String,
    pub owner_id: i32,
}

#[derive(Debug, Deserialize)]
pub struct UpdateTask {
    pub title: Option<String>,
    pub completed: Option<bool>,
}
```

### Migration SQL

```sql
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT false,
    owner_id INTEGER NOT NULL REFERENCES users(id)
);
```

### Route Handlers

```rust
use axum::{
    Router,
    routing::{get, post, put, delete},
    extract::{State, Path, Form},
    response::{Html, Redirect, IntoResponse},
};
use askama::Template;

// list
async fn list_tasks(State(state): State<AppState>) -> Html<String> {
    let tasks = sqlx::query_as::<_, Task>("SELECT * FROM tasks")
        .fetch_all(&state.pool)
        .await
        .expect("query failed");
    let template = TaskListTemplate { tasks };
    Html(template.render().expect("render failed"))
}

// get single
async fn get_task(
    State(state): State<AppState>,
    Path(id): Path<i32>,
) -> Html<String> {
    let task = sqlx::query_as::<_, Task>("SELECT * FROM tasks WHERE id = $1")
        .bind(id)
        .fetch_one(&state.pool)
        .await
        .expect("not found");
    let template = TaskEditTemplate { task };
    Html(template.render().expect("render failed"))
}

// create
async fn create_task(
    State(state): State<AppState>,
    Form(input): Form<CreateTask>,
) -> impl IntoResponse {
    sqlx::query("INSERT INTO tasks (title, owner_id) VALUES ($1, $2)")
        .bind(&input.title)
        .bind(input.owner_id)
        .execute(&state.pool)
        .await
        .expect("insert failed");
    Redirect::to("/")
}

// update
async fn update_task(
    State(state): State<AppState>,
    Path(id): Path<i32>,
    Form(input): Form<UpdateTask>,
) -> impl IntoResponse {
    if let Some(title) = &input.title {
        sqlx::query("UPDATE tasks SET title = $1 WHERE id = $2")
            .bind(title)
            .bind(id)
            .execute(&state.pool)
            .await
            .expect("update failed");
    }
    if let Some(completed) = input.completed {
        sqlx::query("UPDATE tasks SET completed = $1 WHERE id = $2")
            .bind(completed)
            .bind(id)
            .execute(&state.pool)
            .await
            .expect("update failed");
    }
    Redirect::to("/")
}

// delete (returns empty for HTMX to remove element)
async fn delete_task(
    State(state): State<AppState>,
    Path(id): Path<i32>,
) -> Html<&'static str> {
    sqlx::query("DELETE FROM tasks WHERE id = $1")
        .bind(id)
        .execute(&state.pool)
        .await
        .expect("delete failed");
    Html("")
}
```

### Router Setup

```rust
let app = Router::new()
    .route("/", get(list_tasks))
    .route("/new", get(new_form))
    .route("/", post(create_task))
    .route("/{id}/edit", get(get_task))
    .route("/{id}", put(update_task).delete(delete_task))
    .nest_service("/static", ServeDir::new("static"))
    .with_state(state);
```

## Frontend (Askama + HTMX + Alpine.js + PicoCSS)

### Base Template

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}App{% endblock %}</title>
    <link rel="stylesheet" href="https://unpkg.com/@picocss/pico@2/css/pico.min.css">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script defer src="https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js"></script>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
    <nav class="container">
        <ul>
            <li><a href="/"><strong>App</strong></a></li>
        </ul>
    </nav>
    <main class="container">{% block content %}{% endblock %}</main>
</body>
</html>
```

### List Template

```html
{% extends "base.html" %}

{% block content %}
<h1>Tasks</h1>
<a href="/new" role="button">+ New Task</a>

<table>
    <thead>
        <tr>
            <th>Title</th>
            <th>Status</th>
            <th>Actions</th>
        </tr>
    </thead>
    <tbody>
        {% for task in tasks %}
        <tr id="task-{{ task.id }}">
            <td>{{ task.title }}</td>
            <td>{% if task.completed %}Done{% else %}Pending{% endif %}</td>
            <td>
                <a href="/{{ task.id }}/edit">Edit</a>
                <button
                    hx-delete="/{{ task.id }}"
                    hx-target="#task-{{ task.id }}"
                    hx-swap="outerHTML"
                    hx-confirm="Delete this task?"
                >Delete</button>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}
```

### Create Form

```html
{% extends "base.html" %}

{% block content %}
<h1>New Task</h1>

<form method="post" action="/" x-data="{ title: '' }">
    <label>
        Title
        <input type="text" name="title" x-model="title" required>
    </label>

    <button type="submit" :disabled="!title.trim()">Create</button>
</form>

<a href="/">Cancel</a>
{% endblock %}
```

### Edit Form

```html
{% extends "base.html" %}

{% block content %}
<h1>Edit Task</h1>

<form
    hx-put="/{{ task.id }}"
    hx-target="body"
    x-data="{ title: '{{ task.title }}', completed: {{ task.completed }} }"
>
    <label>
        Title
        <input type="text" name="title" x-model="title" required>
    </label>

    <label>
        <input type="checkbox" name="completed" x-model="completed">
        Completed
    </label>

    <button type="submit">Save</button>
</form>

<a href="/">Cancel</a>
{% endblock %}
```

## HTMX Patterns

### Inline Delete

```html
<button
    hx-delete="/{{ id }}"
    hx-target="#item-{{ id }}"
    hx-swap="outerHTML"
    hx-confirm="Are you sure?"
>Delete</button>
```

### Form Submit with Redirect

```html
<form hx-post="/" hx-target="body">
    <!-- HTMX will follow redirect automatically -->
</form>
```

### Partial Update

```html
<div id="results" hx-get="/search?q=..." hx-trigger="keyup changed delay:300ms from:#search">
    <!-- Results loaded here -->
</div>
```

### Loading Indicator

```html
<button hx-get="/slow" hx-indicator="#spinner">
    Load
    <span id="spinner" class="htmx-indicator" aria-busy="true">Loading...</span>
</button>
```

## Alpine.js Patterns

### Form Validation

```html
<form x-data="{ email: '', valid: false }" @submit.prevent="valid && $el.submit()">
    <input type="email" x-model="email" @input="valid = email.includes('@')">
    <button :disabled="!valid">Submit</button>
</form>
```

### Toggle State

```html
<div x-data="{ open: false }">
    <button @click="open = !open">Toggle</button>
    <div x-show="open">Content</div>
</div>
```

### Conditional Classes

```html
<div :class="{ 'completed': completed }">
    Status
</div>
```

## Common Issues

### Askama Template Struct

Every template needs a corresponding Rust struct:

```rust
#[derive(Template)]
#[template(path = "tasks/list.html")]
struct TaskListTemplate {
    tasks: Vec<Task>,
}
```

### Form Data

Use `Form` extractor for form submissions:

```rust
async fn create(Form(input): Form<CreateTask>) -> impl IntoResponse {
    // input.title, etc.
}
```

### HTMX Checkbox

Checkboxes need special handling - they don't send value when unchecked:

```html
<input type="hidden" name="completed" value="false">
<input type="checkbox" name="completed" value="true" {% if task.completed %}checked{% endif %}>
```

### Foreign Keys

Join queries for related data:

```rust
let tasks_with_owners = sqlx::query_as::<_, TaskWithOwner>(
    "SELECT t.*, u.name as owner_name FROM tasks t JOIN users u ON t.owner_id = u.id"
)
.fetch_all(&pool)
.await?;
```
