use eyre::{Result, bail};
use serde::Deserialize;
use std::collections::HashMap;
use std::path::{Component, Path, PathBuf};

#[derive(Debug, Clone)]
pub enum AgentBackend {
    Claude,
    OpenCode,
}

/// Parsed from a "backend" or "backend/model" string, e.g. "claude", "opencode/kimi-k2.5-free"
#[derive(Debug, Clone)]
pub struct AgentConfig {
    pub backend: AgentBackend,
    pub model: Option<String>,
}

impl Default for AgentConfig {
    fn default() -> Self {
        Self {
            backend: AgentBackend::Claude,
            model: None,
        }
    }
}

impl<'de> serde::Deserialize<'de> for AgentConfig {
    fn deserialize<D>(deserializer: D) -> std::result::Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        // "backend" or "backend:model" — e.g. "claude", "opencode:opencode/kimi-k2.5-free"
        let (backend_str, model) = match s.split_once(':') {
            Some((b, m)) => (b, Some(m.to_string())),
            None => (s.as_str(), None),
        };
        let backend = match backend_str {
            "claude" => AgentBackend::Claude,
            "opencode" => AgentBackend::OpenCode,
            other => {
                return Err(serde::de::Error::custom(format!(
                    "unknown agent backend: '{other}' (expected 'claude' or 'opencode')"
                )));
            }
        };
        Ok(AgentConfig { backend, model })
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct ForgeConfig {
    #[serde(default)]
    pub agent: AgentConfig,
    pub container: ContainerConfig,
    pub project: ProjectConfig,
    pub steps: StepsConfig,
    #[serde(default)]
    pub patch: PatchConfig,
    /// extra host paths to expose to runtime
    #[serde(default)]
    pub mounts: Vec<MountConfig>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct MountConfig {
    /// host path (~ is expanded to $HOME)
    pub host: String,
    /// absolute path inside the container
    pub container: String,
    /// local runtime target path relative to project.workdir
    #[serde(default)]
    pub local_target: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PatchConfig {
    /// glob patterns to exclude from the output patch (git pathspec exclude)
    #[serde(default = "default_patch_excludes")]
    pub exclude: Vec<String>,
}

impl Default for PatchConfig {
    fn default() -> Self {
        Self {
            exclude: default_patch_excludes(),
        }
    }
}

fn default_patch_excludes() -> Vec<String> {
    vec![
        "tasks.md".into(),
        "opencode.json".into(),
        "*SUMMARY*.md".into(),
        "*REPORT*.md".into(),
        "*_venv*".into(),
        "*venv*/**".into(),
        "__pycache__/**".into(),
        "target/**".into(),
        "node_modules/**".into(),
    ]
}

#[derive(Debug, Clone, Deserialize)]
pub struct ContainerConfig {
    pub image: String,
    pub setup: Vec<String>,
    pub user: String,
    pub user_setup: String,
    #[serde(default)]
    pub env: HashMap<String, String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ProjectConfig {
    pub language: String,
    pub source: String,
    pub workdir: String,
    /// glob patterns to exclude when mounting source into container
    #[serde(default)]
    pub exclude: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct StepsConfig {
    pub validate: Vec<ValidateStep>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ValidateStep {
    pub name: String,
    pub command: String,
}

impl ForgeConfig {
    pub fn load(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path)
            .map_err(|e| eyre::eyre!("failed to read config {}: {e}", path.display()))?;
        let config: ForgeConfig = toml::from_str(&content)
            .map_err(|e| eyre::eyre!("failed to parse config {}: {e}", path.display()))?;
        config.validate()?;
        Ok(config)
    }

    pub fn default_rust() -> Self {
        Self {
            agent: AgentConfig::default(),
            container: ContainerConfig {
                image: "rust:latest".into(),
                setup: vec!["apt-get update && apt-get install -y curl sudo git".into()],
                user: "forge".into(),
                user_setup: concat!(
                    "useradd -m -s /bin/bash forge",
                    " && echo 'forge ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers",
                    " && cp -r /usr/local/cargo /home/forge/.cargo",
                    " && cp -r /usr/local/rustup /home/forge/.rustup",
                    " && chown -R forge:forge /home/forge/.cargo /home/forge/.rustup",
                )
                .into(),
                env: HashMap::from([
                    ("PATH".into(), "/home/forge/.local/bin:/home/forge/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin".into()),
                    ("CARGO_HOME".into(), "/home/forge/.cargo".into()),
                    ("RUSTUP_HOME".into(), "/home/forge/.rustup".into()),
                ]),
            },
            project: ProjectConfig {
                language: "rust".into(),
                source: ".".into(),
                workdir: "/app".into(),
                exclude: default_excludes(),
            },
            patch: PatchConfig::default(),
            mounts: vec![],
            steps: StepsConfig {
                validate: vec![
                    ValidateStep {
                        name: "check".into(),
                        command: "cargo check 2>&1".into(),
                    },
                    ValidateStep {
                        name: "test".into(),
                        command: "cargo test 2>&1".into(),
                    },
                    ValidateStep {
                        name: "bench".into(),
                        command: "cargo bench 2>&1".into(),
                    },
                ],
            },
        }
    }

    fn validate(&self) -> Result<()> {
        if self.container.image.is_empty() {
            bail!("container.image must not be empty");
        }
        if self.container.user.is_empty() {
            bail!("container.user must not be empty");
        }
        if self.project.language.is_empty() {
            bail!("project.language must not be empty");
        }
        if self.project.workdir.is_empty() {
            bail!("project.workdir must not be empty");
        }
        if self.steps.validate.is_empty() {
            bail!("steps.validate must have at least one step");
        }
        for m in &self.mounts {
            if m.host.is_empty() {
                bail!("mount host path must not be empty");
            }
            if !m.container.starts_with('/') {
                bail!(
                    "mount container path must be absolute, got: '{}'",
                    m.container
                );
            }
            if let Some(local) = &m.local_target {
                if local.is_empty() {
                    bail!("mount local_target must not be empty");
                }
                normalize_relative_path(local)?;
            }
        }
        Ok(())
    }
}

fn default_excludes() -> Vec<String> {
    vec![
        ".git".into(),
        "**/.git".into(),
        "**/.git/**".into(),
        "target".into(),
        "**/target".into(),
        "**/target/**".into(),
        "node_modules".into(),
        "**/node_modules".into(),
        "**/node_modules/**".into(),
        ".venv".into(),
        "**/.venv".into(),
        "**/.venv/**".into(),
        "__pycache__".into(),
        "**/__pycache__".into(),
        "**/__pycache__/**".into(),
    ]
}

impl PatchConfig {
    /// build git pathspec exclusion args: `-- . ':(exclude)pat1' ':(exclude)pat2' ...`
    pub fn git_diff_pathspec(&self) -> String {
        let mut spec = String::from("-- .");
        for pat in &self.exclude {
            spec.push_str(&format!(" ':(exclude){pat}'"));
        }
        spec
    }
}

impl MountConfig {
    /// resolve host path relative to config_dir, with ~ expansion
    pub fn resolve_host_path(&self, config_dir: &Path) -> Result<PathBuf> {
        let path = if self.host.starts_with('~') {
            let home = std::env::var("HOME")
                .map_err(|_| eyre::eyre!("HOME not set, cannot expand ~ in mount path"))?;
            PathBuf::from(self.host.replacen('~', &home, 1))
        } else {
            config_dir.join(&self.host)
        };
        if !path.exists() {
            bail!("mount host path does not exist: {}", path.display());
        }
        Ok(path)
    }

    pub fn resolve_local_target(&self) -> Result<Option<PathBuf>> {
        self.local_target
            .as_deref()
            .map(normalize_relative_path)
            .transpose()
    }
}

/// resolve source path relative to the config file's directory
pub fn resolve_source_path(config: &ForgeConfig, config_dir: &Path) -> Result<PathBuf> {
    let source = &config.project.source;
    let resolved = config_dir.join(source);
    if !resolved.exists() {
        bail!(
            "source path does not exist: {} (resolved from '{}')",
            resolved.display(),
            source
        );
    }
    Ok(resolved)
}

fn normalize_relative_path(path: &str) -> Result<PathBuf> {
    let mut out = PathBuf::new();
    for component in Path::new(path).components() {
        match component {
            Component::Prefix(_) => bail!("windows paths are not supported"),
            Component::RootDir => bail!("local_target must be relative, got: '{path}'"),
            Component::CurDir => {}
            Component::Normal(segment) => out.push(segment),
            Component::ParentDir => {
                bail!("path traversal is not allowed in local_target: '{path}'")
            }
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_agent_config_deserialize_claude_no_model() {
        let config: AgentConfig = serde_json::from_str("\"claude\"").unwrap();
        assert!(matches!(config.backend, AgentBackend::Claude));
        assert_eq!(config.model, None);
    }

    #[test]
    fn test_agent_config_deserialize_claude_with_model() {
        let config: AgentConfig =
            serde_json::from_str("\"claude:claude-sonnet-4-5-20250929\"").unwrap();
        assert!(matches!(config.backend, AgentBackend::Claude));
        assert_eq!(config.model, Some("claude-sonnet-4-5-20250929".to_string()));
    }

    #[test]
    fn test_agent_config_deserialize_opencode_with_model() {
        let config: AgentConfig =
            serde_json::from_str("\"opencode:opencode/kimi-k2.5-free\"").unwrap();
        assert!(matches!(config.backend, AgentBackend::OpenCode));
        assert_eq!(config.model, Some("opencode/kimi-k2.5-free".to_string()));
    }

    #[test]
    fn test_agent_config_deserialize_opencode_no_model() {
        let config: AgentConfig = serde_json::from_str("\"opencode\"").unwrap();
        assert!(matches!(config.backend, AgentBackend::OpenCode));
        assert_eq!(config.model, None);
    }

    #[test]
    fn test_agent_config_deserialize_invalid_backend() {
        let result: Result<AgentConfig, _> = serde_json::from_str("\"invalid-backend\"");
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(err.contains("unknown agent backend"));
        assert!(err.contains("invalid-backend"));
    }

    #[test]
    fn test_agent_backend_variants() {
        // Ensure we can create both variants
        let claude = AgentBackend::Claude;
        let opencode = AgentBackend::OpenCode;

        // Test that they are different variants
        assert!(!matches!(claude, AgentBackend::OpenCode));
        assert!(!matches!(opencode, AgentBackend::Claude));
    }

    #[test]
    fn test_agent_config_default() {
        let config = AgentConfig::default();
        assert!(matches!(config.backend, AgentBackend::Claude));
        assert_eq!(config.model, None);
    }
}
