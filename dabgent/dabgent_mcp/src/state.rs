use chrono::{DateTime, Utc};
use eyre::{eyre, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

const STATE_FILE_NAME: &str = ".dabgent_state";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "state", content = "data")]
pub enum ProjectState {
    Scaffolded,
    Validated {
        validated_at: DateTime<Utc>,
        checksum: String,
    },
    Deployed {
        validated_at: DateTime<Utc>,
        checksum: String,
        deployed_at: DateTime<Utc>,
    },
}

impl ProjectState {
    pub fn new() -> Self {
        Self::Scaffolded
    }

    pub fn validate(self, checksum: String) -> Result<Self> {
        match self {
            Self::Scaffolded | Self::Validated { .. } | Self::Deployed { .. } => {
                Ok(Self::Validated {
                    validated_at: Utc::now(),
                    checksum,
                })
            }
        }
    }

    pub fn deploy(self) -> Result<Self> {
        match self {
            Self::Validated { validated_at, checksum } => Ok(Self::Deployed {
                validated_at,
                checksum,
                deployed_at: Utc::now(),
            }),
            Self::Scaffolded => Err(eyre!("cannot deploy: project not validated")),
            Self::Deployed { .. } => Err(eyre!("cannot deploy: project already deployed (re-validate first)")),
        }
    }

    pub fn checksum(&self) -> Option<&str> {
        match self {
            Self::Validated { checksum, .. } | Self::Deployed { checksum, .. } => Some(checksum),
            _ => None,
        }
    }

    pub fn is_validated(&self) -> bool {
        matches!(self, Self::Validated { .. } | Self::Deployed { .. })
    }
}

/// load state from work_dir/.dabgent_state
pub fn load_state(work_dir: &Path) -> Result<Option<ProjectState>> {
    let state_path = work_dir.join(STATE_FILE_NAME);

    if !state_path.exists() {
        return Ok(None);
    }

    let content = fs::read_to_string(&state_path)
        .map_err(|e| eyre!("failed to read state file: {}", e))?;

    let state: ProjectState = serde_json::from_str(&content)
        .map_err(|e| eyre!("failed to parse state file: {}", e))?;

    Ok(Some(state))
}

/// save state to work_dir/.dabgent_state atomically
pub fn save_state(work_dir: &Path, state: &ProjectState) -> Result<()> {
    let state_path = work_dir.join(STATE_FILE_NAME);
    let temp_path = work_dir.join(format!("{}.tmp", STATE_FILE_NAME));

    let content = serde_json::to_string_pretty(state)
        .map_err(|e| eyre!("failed to serialize state: {}", e))?;

    fs::write(&temp_path, content)
        .map_err(|e| eyre!("failed to write temp state file: {}", e))?;

    fs::rename(&temp_path, &state_path)
        .map_err(|e| eyre!("failed to rename temp state file: {}", e))?;

    Ok(())
}

/// compute BLAKE3 checksum of critical project files
pub fn compute_checksum(work_dir: &Path) -> Result<String> {
    let mut files_to_hash = Vec::new();

    // critical files
    let package_json = work_dir.join("package.json");
    if package_json.exists() {
        files_to_hash.push(package_json);
    }

    // collect all .ts and .tsx files in client/ and server/
    for dir in &["client", "server"] {
        let dir_path = work_dir.join(dir);
        if dir_path.exists() {
            collect_ts_files(&dir_path, &mut files_to_hash)?;
        }
    }

    // sort files deterministically
    files_to_hash.sort();

    if files_to_hash.is_empty() {
        return Err(eyre!("no files to hash - project structure appears invalid"));
    }

    // compute combined hash
    let mut hasher = blake3::Hasher::new();

    for file_path in files_to_hash {
        let content = fs::read(&file_path)
            .map_err(|e| eyre!("failed to read {}: {}", file_path.display(), e))?;
        hasher.update(&content);
    }

    Ok(hasher.finalize().to_hex().to_string())
}

/// verify checksum matches current project state
pub fn verify_checksum(work_dir: &Path, expected: &str) -> Result<bool> {
    let current = compute_checksum(work_dir)?;
    Ok(current == expected)
}

/// recursively collect .ts and .tsx files from directory
fn collect_ts_files(dir: &Path, files: &mut Vec<PathBuf>) -> Result<()> {
    if !dir.is_dir() {
        return Ok(());
    }

    let entries = fs::read_dir(dir)
        .map_err(|e| eyre!("failed to read directory {}: {}", dir.display(), e))?;

    for entry in entries {
        let entry = entry.map_err(|e| eyre!("failed to read directory entry: {}", e))?;
        let path = entry.path();

        if path.is_dir() {
            collect_ts_files(&path, files)?;
        } else if let Some(ext) = path.extension() {
            if ext == "ts" || ext == "tsx" {
                files.push(path);
            }
        }
    }

    Ok(())
}
