# Route Handlers

## AppError Type

The template includes `AppError` for proper error handling. All handlers return `Result<T, AppError>`.

```rust
pub struct AppError(anyhow::Error);

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        tracing::error!("Application error: {}", self.0);
        (StatusCode::INTERNAL_SERVER_ERROR, "Something went wrong").into_response()
    }
}

impl<E> From<E> for AppError
where
    E: Into<anyhow::Error>,
{
    fn from(err: E) -> Self {
        Self(err.into())
    }
}
```

## CRUD Handlers

All handlers use `?` operator - **never `.expect()` or `.unwrap()`**.

```rust
use axum::{
    extract::{State, Path, Form},
    response::{Html, Redirect, IntoResponse},
};
use askama::Template;

// LIST
async fn list_tasks(State(state): State<AppState>) -> Result<Html<String>, AppError> {
    let tasks = sqlx::query_as!(Task, "SELECT id, title, completed FROM tasks")
        .fetch_all(&state.pool)
        .await?;
    let template = IndexTemplate { tasks };
    Ok(Html(template.render()?))
}

// GET SINGLE
async fn get_task(
    State(state): State<AppState>,
    Path(id): Path<i32>,
) -> Result<Html<String>, AppError> {
    let task = sqlx::query_as!(Task, "SELECT id, title, completed FROM tasks WHERE id = $1", id)
        .fetch_optional(&state.pool)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Task not found"))?;
    let template = EditTemplate { task };
    Ok(Html(template.render()?))
}

// CREATE
async fn create_task(
    State(state): State<AppState>,
    Form(input): Form<CreateTask>,
) -> Result<impl IntoResponse, AppError> {
    sqlx::query!("INSERT INTO tasks (title) VALUES ($1)", input.title)
        .execute(&state.pool)
        .await?;
    Ok(Redirect::to("/"))
}

// UPDATE
async fn update_task(
    State(state): State<AppState>,
    Path(id): Path<i32>,
    Form(input): Form<UpdateTask>,
) -> Result<impl IntoResponse, AppError> {
    let result = sqlx::query!(
        "UPDATE tasks SET title = COALESCE($1, title), completed = COALESCE($2, completed) WHERE id = $3",
        input.title,
        input.completed,
        id
    )
    .execute(&state.pool)
    .await?;

    if result.rows_affected() == 0 {
        return Err(anyhow::anyhow!("Task not found").into());
    }
    Ok(Redirect::to("/"))
}

// DELETE (returns empty for HTMX to remove element)
async fn delete_task(
    State(state): State<AppState>,
    Path(id): Path<i32>,
) -> Result<Html<&'static str>, AppError> {
    let result = sqlx::query!("DELETE FROM tasks WHERE id = $1", id)
        .execute(&state.pool)
        .await?;

    if result.rows_affected() == 0 {
        return Err(anyhow::anyhow!("Task not found").into());
    }
    Ok(Html(""))
}
```

## Router Setup

```rust
let app = Router::new()
    .route("/", get(list_tasks).post(create_task))
    .route("/new", get(new_form))
    .route("/{id}/edit", get(get_task))
    .route("/{id}", post(update_task).delete(delete_task))
    .nest_service("/static", ServeDir::new("static"))
    .with_state(state);
```

## Transactions

Use when multiple queries must succeed together:

```rust
async fn vote(
    State(state): State<AppState>,
    Form(input): Form<VoteInput>,
) -> Result<impl IntoResponse, AppError> {
    let mut tx = state.pool.begin().await?;

    // insert vote
    sqlx::query!("INSERT INTO votes (user_id, option_id) VALUES ($1, $2)",
        input.user_id, input.option_id)
        .execute(&mut *tx)
        .await?;

    // increment count
    sqlx::query!("UPDATE options SET count = count + 1 WHERE id = $1", input.option_id)
        .execute(&mut *tx)
        .await?;

    tx.commit().await?;  // atomic commit
    Ok(Redirect::to("/"))
}
```

## Error Inspection

Don't use `is_err()` blindly - inspect actual error type:

```rust
// BAD - returns "already voted" for ANY error
if result.is_err() {
    return Err(AppError::internal("Already voted"));
}

// GOOD - inspect actual error type
match result {
    Ok(_) => Ok(Html("Vote recorded!")),
    Err(sqlx::Error::Database(e)) if e.is_unique_violation() => {
        Err(anyhow::anyhow!("Already voted").into())
    }
    Err(e) => Err(e.into()),  // propagate real errors
}
```
