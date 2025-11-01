use eyre::Result;
use rust_embed::RustEmbed;
use std::path::{Path, PathBuf};

pub trait Template: TemplateCore {
    fn name(&self) -> String;
}

pub trait TemplateCore {
    fn description(&self) -> Option<String>;
    fn extract(&self, work_dir: &Path) -> Result<Vec<PathBuf>>;
}

impl<T: RustEmbed> TemplateCore for T {
    fn description(&self) -> Option<String> {
        Self::get("CLAUDE.md").map(|file| String::from_utf8_lossy(&file.data).to_string())
    }

    fn extract(&self, work_dir: &Path) -> Result<Vec<PathBuf>> {
        let mut files = Vec::new();
        for path in Self::iter().filter(|p| !p.is_empty()) {
            if let Some(file) = Self::get(path.as_ref()) {
                let content = String::from_utf8_lossy(&file.data);
                files.push((path.to_string(), content.to_string()));
            }
        }
        files.sort_by(|a, b| a.0.cmp(&b.0));

        let mut extracted = Vec::new();
        for (path, content) in files {
            let written_path = write_file(work_dir, &path, &content)?;
            extracted.push(written_path);
        }
        Ok(extracted)
    }
}

pub fn write_file(work_dir: &Path, path: &str, content: &str) -> Result<PathBuf> {
    let full_path = work_dir.join(path);
    if let Some(parent) = full_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| {
            eyre::eyre!(
                "failed to create directory '{}' for file '{}': {}",
                parent.display(),
                full_path.display(),
                e
            )
        })?;
    }
    std::fs::write(&full_path, content)
        .map_err(|e| eyre::eyre!("failed to write file '{}': {}", full_path.display(), e))?;
    Ok(full_path)
}
