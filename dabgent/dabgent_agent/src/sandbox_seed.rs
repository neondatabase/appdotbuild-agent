use dabgent_sandbox::SandboxDyn;
use eyre::Result;
use sha2::{Digest, Sha256};
use std::path::Path;

/// Files collected from a template along with a deterministic hash.
///
/// - `files`: Vec of (sandbox_path, content)
/// - `hash`: sha256 over the concatenation of "path\ncontent\n" for every file in `files`
///
/// Paths are normalized to the sandbox target by prefixing `base_sandbox_path` to the relative path
/// within the template root.
pub struct TemplateFiles {
    pub files: Vec<(String, String)>,
    pub hash: String,
}

/// Default directories to skip when collecting files from a template.
pub const DEFAULT_TEMPLATE_SKIP_DIRS: &[&str] = &["node_modules", ".git", ".venv", "target", "dist", "build"];

/// Recursively collect all text files from `template_path`, mapping them under `base_sandbox_path`,
/// and compute a deterministic content hash.
///
/// Binary files (that cannot be read as UTF-8 text) are skipped.
pub fn collect_template_files(template_path: &Path, base_sandbox_path: &str) -> Result<TemplateFiles> {
    let mut files: Vec<(String, String)> = Vec::new();
    walk_collect(template_path, template_path, base_sandbox_path, &mut files, DEFAULT_TEMPLATE_SKIP_DIRS)?;
    files.sort_by(|a, b| a.0.cmp(&b.0));

    let hash = compute_template_hash(&files);
    Ok(TemplateFiles { files, hash })
}

/// Compute a deterministic hash for a set of (path, content) pairs.
/// The format used is sha256 over "path\ncontent\n" for each pair, in order.
pub fn compute_template_hash(files: &[(String, String)]) -> String {
    let mut hasher = Sha256::new();
    for (p, c) in files {
        hasher.update(p.as_bytes());
        hasher.update(b"\n");
        hasher.update(c.as_bytes());
        hasher.update(b"\n");
    }
    hex::encode(hasher.finalize())
}

/// Write collected template files into the sandbox, returning the count of files written.
pub async fn write_template_files(sandbox: &mut Box<dyn SandboxDyn>, files: &[(String, String)]) -> Result<usize> {
    let refs: Vec<(&str, &str)> = files.iter().map(|(p, c)| (p.as_str(), c.as_str())).collect();
    sandbox.write_files(refs).await?;
    Ok(files.len())
}

fn walk_collect(
    dir_path: &Path,
    template_root: &Path,
    base_sandbox_path: &str,
    out: &mut Vec<(String, String)>,
    skip_dirs: &[&str],
) -> Result<()> {
    for entry in std::fs::read_dir(dir_path)? {
        let entry = entry?;
        let path = entry.path();

        if path.is_dir() {
            let dir_name = path.file_name().unwrap().to_string_lossy();
            if skip_dirs.contains(&dir_name.as_ref()) {
                continue;
            }
            walk_collect(&path, template_root, base_sandbox_path, out, skip_dirs)?;
        } else if path.is_file() {
            let rel_path = path.strip_prefix(template_root)?;
            let sandbox_path = format!("{}/{}", base_sandbox_path, rel_path.to_string_lossy());
            match std::fs::read_to_string(&path) {
                Ok(content) => out.push((sandbox_path, content)),
                Err(_) => {
                    // Likely a binary file; skip it.
                    tracing::warn!("Skipping non-text file during template collection: {:?}", path);
                }
            }
        }
    }
    Ok(())
}