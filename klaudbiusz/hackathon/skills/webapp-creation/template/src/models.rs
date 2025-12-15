use serde::{Deserialize, Serialize};
use sqlx::FromRow;

// example model - replace with your own
//
// #[derive(Debug, Clone, FromRow, Serialize)]
// pub struct Item {
//     pub id: i64,
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
#[derive(Debug, Clone, FromRow, Serialize, Deserialize)]
pub struct Placeholder {
    pub id: i64,
}
