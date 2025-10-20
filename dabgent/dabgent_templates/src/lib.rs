use rust_embed::Embed;

#[derive(Embed)]
#[folder = "template_trpc"]
#[exclude = ".git/**"]
#[exclude = "**/node_modules/**"]
#[exclude = "target/**"]
#[exclude = "dist/**"]
#[exclude = "build/**"]
#[exclude = "**/.DS_Store"]
pub struct TemplateTRPC;
