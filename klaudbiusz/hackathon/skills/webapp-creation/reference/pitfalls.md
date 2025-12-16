# Critical Pitfalls

## NEVER use .expect() or .unwrap() in Handlers

These cause **server crashes** on any error:

```rust
// WRONG - crashes server
let tasks = sqlx::query_as::<_, Task>("SELECT * FROM tasks")
    .fetch_all(&pool)
    .await
    .expect("query failed");  // PANIC!

// CORRECT - returns error response
let tasks = sqlx::query_as!(Task, "SELECT id, title, completed FROM tasks")
    .fetch_all(&pool)
    .await?;  // propagates error via AppError
```

## Route Parameters: {param} not :param

Axum 0.7+ uses `{param}` syntax. Using `:param` **passes cargo check but panics at runtime**:

```rust
// WRONG - compiles but panics at startup
.route("/:id/edit", get(edit_form))
.route("/:id", post(update).delete(delete))

// CORRECT - Axum 0.7+ syntax
.route("/{id}/edit", get(edit_form))
.route("/{id}", post(update).delete(delete))
```

## All Handlers Must Return Result<T, AppError>

```rust
// WRONG - no error handling
async fn list(State(state): State<AppState>) -> Html<String> {
    let tasks = sqlx::query_as!(Task, "...").fetch_all(&state.pool).await.unwrap();
    Html(template.render().unwrap())
}

// CORRECT - proper error handling
async fn list(State(state): State<AppState>) -> Result<Html<String>, AppError> {
    let tasks = sqlx::query_as!(Task, "...").fetch_all(&state.pool).await?;
    Ok(Html(template.render()?))
}
```

## Option<T> in Askama Templates

Askama can't handle `Option<T>` in conditionals directly:

```rust
// WRONG - won't compile
struct IndexTemplate {
    user: Option<User>,  // {% if user %} fails
}

// CORRECT - extract in handler
struct IndexTemplate {
    is_authenticated: bool,
    user_email: String,
}

async fn index(Extension(user): Extension<Option<User>>) -> Result<Html<String>, AppError> {
    let (is_authenticated, user_email) = match user {
        Some(u) => (true, u.email),
        None => (false, String::new()),
    };
    // ...
}
```

Alternative: use match syntax in template:
```html
{% match user %}
{% when Some with (u) %}Hello, {{ u.email }}{% when None %}Guest{% endmatch %}
```

## Don't Use is_err() Blindly

```rust
// WRONG - hides real errors
if result.is_err() {
    return Err(AppError::internal("Already voted"));
}

// CORRECT - inspect actual error
match result {
    Ok(_) => Ok(Html("Success")),
    Err(sqlx::Error::Database(e)) if e.is_unique_violation() => {
        Err(anyhow::anyhow!("Already voted").into())
    }
    Err(e) => Err(e.into()),  // propagate real errors
}
```

## PostgreSQL Type Mapping

- `SERIAL` → `i32` (use for most tables)
- `BIGSERIAL` → `i64` (only for billions of rows)

Mismatched types compile but cause runtime confusion.

## Check rows_affected() for Updates/Deletes

```rust
let result = sqlx::query!("DELETE FROM tasks WHERE id = $1", id)
    .execute(&state.pool)
    .await?;

if result.rows_affected() == 0 {
    return Err(anyhow::anyhow!("Not found").into());
}
```

## Transactions for Atomic Operations

Multiple related queries must use transactions:

```rust
let mut tx = state.pool.begin().await?;

sqlx::query!("INSERT INTO votes ...").execute(&mut *tx).await?;
sqlx::query!("UPDATE options SET count = count + 1 ...").execute(&mut *tx).await?;

tx.commit().await?;  // all or nothing
```
