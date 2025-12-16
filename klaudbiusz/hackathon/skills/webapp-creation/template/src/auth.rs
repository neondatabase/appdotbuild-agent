use axum::{
    extract::{Request, State},
    middleware::Next,
    response::Response,
};
use axum_extra::extract::CookieJar;
use sqlx::FromRow;

use crate::db::DbPool;

#[derive(Debug, Clone, FromRow)]
pub struct User {
    pub id: String,
    pub email: String,
    pub name: Option<String>,
    pub image: Option<String>,
}

pub async fn auth_middleware(
    State(pool): State<DbPool>,
    jar: CookieJar,
    mut request: Request,
    next: Next,
) -> Response {
    let user = extract_user(&pool, &jar).await;
    request.extensions_mut().insert(user);
    next.run(request).await
}

async fn extract_user(pool: &DbPool, jar: &CookieJar) -> Option<User> {
    // cookie name: "better-auth.session_token" (dev) or "__Secure-better-auth.session_token" (prod)
    let token = jar
        .get("better-auth.session_token")
        .or_else(|| jar.get("__Secure-better-auth.session_token"))?
        .value();

    sqlx::query_as::<_, User>(
        r#"
        SELECT u.id, u.email, u.name, u.image
        FROM neon_auth.user u
        JOIN neon_auth.session s ON s."userId" = u.id
        WHERE s.token = $1 AND s."expiresAt" > NOW()
        "#,
    )
    .bind(token)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten()
}
