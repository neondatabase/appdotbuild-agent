pub use crate::template::*;
use eyre::Result;
use ignore::Walk;
use std::path::{Path, PathBuf};

pub struct LocalTemplate {
    pub name: String,
    pub template_dir: std::path::PathBuf,
}

impl LocalTemplate {
    pub fn from_dir(name: &str, path: &Path) -> Result<Self> {
        if !path.exists() || !path.is_dir() {
            return Err(eyre::eyre!(
                "Provided template path '{}' does not exist or is not a directory",
                path.display()
            ));
        }
        Ok(Self {
            name: name.to_string(),
            template_dir: path.to_path_buf(),
        })
    }
}

impl Template for LocalTemplate {
    fn name(&self) -> String {
        self.name.clone()
    }
}

impl TemplateCore for LocalTemplate {
    fn description(&self) -> Option<String> {
        let claude_path = self.template_dir.join("CLAUDE.md");
        if claude_path.exists() {
            match std::fs::read_to_string(claude_path) {
                Ok(content) => Some(content),
                Err(_) => None,
            }
        } else {
            None
        }
    }

    fn extract(&self, work_dir: &Path) -> Result<Vec<PathBuf>> {
        let mut files = Vec::new();
        for entry in Walk::new(work_dir) {
            if let Ok(entry) = entry {
                if entry.file_type().map_or(false, |ft| ft.is_file()) {
                    let path = entry.path().strip_prefix(&self.template_dir)?;
                    let content = std::fs::read_to_string(entry.path())?;
                    files.push((path.to_string_lossy().to_string(), content));
                }
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
