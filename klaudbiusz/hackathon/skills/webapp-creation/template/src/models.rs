use serde::{Deserialize, Serialize};

// example model - replace with your own
// note: FromRow derive is NOT needed when using sqlx::query_as! macro
// the macro generates field mapping at compile time from column names
//
// #[derive(Debug, Clone, Serialize)]
// pub struct Item {
//     pub id: i32,  // SERIAL in PostgreSQL maps to i32 (use BIGSERIAL for i64)
//     pub name: String,
//     pub completed: bool,
// }
//
// #[derive(Debug, Deserialize)]
// pub struct CreateItem {
//     pub name: String,
// }
//
// #[derive(Debug, Deserialize)]
// pub struct UpdateItem {
//     pub name: Option<String>,
//     pub completed: Option<bool>,
// }

// placeholder to make the module non-empty
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Placeholder {
    pub id: i32,  // SERIAL in PostgreSQL maps to i32
}
