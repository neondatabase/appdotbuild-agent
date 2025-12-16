# Data Modeling

## SQLx Query Style

**Always use compile-time checked macros** (`query!`, `query_as!`) instead of runtime functions:

```rust
// GOOD - compile-time checked, catches SQL errors early
let tasks = sqlx::query_as!(Task, "SELECT id, title, completed FROM tasks")
    .fetch_all(&pool)
    .await?;

sqlx::query!("INSERT INTO tasks (title) VALUES ($1)", input.title)
    .execute(&pool)
    .await?;

// AVOID - runtime only, SQL errors discovered at runtime
let tasks = sqlx::query_as::<_, Task>("SELECT * FROM tasks")
    .fetch_all(&pool)
    .await?;
```

Benefits:
- SQL syntax validated at compile time
- Column types checked against Rust struct
- Typos in column/table names caught immediately

**Requirement**: Database schema must exist at compile time. Run `./scripts/neon-setup` before `cargo build`.

## Model Structs

```rust
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

// read model - maps to database row
#[derive(Debug, Clone, FromRow, Serialize)]
pub struct Task {
    pub id: i32,
    pub title: String,
    pub completed: bool,
}

// create DTO - form input for new records
#[derive(Debug, Deserialize)]
pub struct CreateTask {
    pub title: String,
}

// update DTO - optional fields for partial updates
#[derive(Debug, Deserialize)]
pub struct UpdateTask {
    pub title: Option<String>,
    pub completed: Option<bool>,
}
```

## Migrations

Place SQL in `migrations/001_init.sql`:

```sql
CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL
);

-- foreign key example
CREATE TABLE IF NOT EXISTS comments (
    id SERIAL PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    body TEXT NOT NULL
);
```

## PostgreSQL Type Mapping

| PostgreSQL | Rust | Use Case |
|------------|------|----------|
| `SERIAL` | `i32` | Most tables (up to 2B rows) |
| `BIGSERIAL` | `i64` | Only if you need billions of rows |
| `TEXT` | `String` | Variable-length strings |
| `BOOLEAN` | `bool` | True/false |
| `TIMESTAMP` | `chrono::NaiveDateTime` | Date/time (add `chrono` feature to sqlx) |

Using wrong type compiles but causes runtime confusion.

## Join Queries

For related data, create a combined struct:

```rust
#[derive(Debug, FromRow, Serialize)]
pub struct TaskWithOwner {
    pub id: i32,
    pub title: String,
    pub owner_name: String,
}

// in handler
let tasks = sqlx::query_as!(
    TaskWithOwner,
    "SELECT t.id, t.title, u.name as owner_name
     FROM tasks t JOIN users u ON t.owner_id = u.id"
)
.fetch_all(&pool)
.await?;
```
