use eyre::Result;
use rust_embed::RustEmbed;
use std::path::{Path, PathBuf};

#[derive(RustEmbed)]
#[folder = "templates/maturin_base"]
pub struct TemplateMaturin;

impl TemplateMaturin {
    pub fn guidelines() -> String {
        // Read from GUIDELINES.md in the embedded template
        if let Some(file) = Self::get("GUIDELINES.md") {
            // Safety: We control the template files and know they're valid UTF-8
            return String::from_utf8_lossy(&file.data).to_string();
        }
        "Error: Guidelines not found in template".to_string()
    }
}

/// Extract all template files and write them to the target directory
pub fn extract_template_files(target_dir: &Path) -> Result<Vec<PathBuf>> {
    let mut copied_files = Vec::new();

    for path in TemplateMaturin::iter() {
        let path_str = path.as_ref();

        // Skip GUIDELINES.md - we return it as text, not write it
        if path_str == "GUIDELINES.md" {
            continue;
        }

        if let Some(file) = TemplateMaturin::get(path_str) {
            let target_file = target_dir.join(path_str);

            // Ensure parent directory exists
            if let Some(parent) = target_file.parent() {
                std::fs::create_dir_all(parent).map_err(|e| {
                    eyre::eyre!(
                        "failed to create directory '{}': {}",
                        parent.display(),
                        e
                    )
                })?;
            }

            // Write file
            std::fs::write(&target_file, &file.data).map_err(|e| {
                eyre::eyre!("failed to write file '{}': {}", target_file.display(), e)
            })?;

            copied_files.push(target_file);
        }
    }

    copied_files.sort();
    Ok(copied_files)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_guidelines_exist() {
        let guidelines = TemplateMaturin::guidelines();
        assert!(guidelines.contains("PyO3"));
        assert!(guidelines.contains("Type Mapping"));
    }

    #[test]
    fn test_template_files_exist() {
        // Check that key files are embedded
        assert!(TemplateMaturin::get("Cargo.toml").is_some());
        assert!(TemplateMaturin::get("pyproject.toml").is_some());
        assert!(TemplateMaturin::get("src/lib.rs").is_some());
        assert!(TemplateMaturin::get("GUIDELINES.md").is_some());
    }
}
