use rust_embed::Embed;

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

impl TemplateTRPC {
    pub fn guidelines() -> &'static str {
        include_str!("../template_trpc/CLAUDE.md")
    }
}
