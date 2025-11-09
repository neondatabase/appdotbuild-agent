use rust_embed::Embed;
pub mod capabilities;
pub mod local;
pub mod merge;
pub mod template;
pub use local::LocalTemplate;
pub use template::{Template, TemplateCore};

#[derive(Embed)]
#[folder = "template_trpc"]
#[exclude = ".git/**"]
#[exclude = "**/node_modules/**"]
#[exclude = "target/**"]
#[exclude = "**/dist/**"]
#[exclude = "server/public"]
#[exclude = "build/**"]
#[exclude = "**/.DS_Store"]
pub struct TemplateTRPC;

impl Template for TemplateTRPC {
    fn name(&self) -> String {
        "tRPC TypeScript".to_string()
    }
}
