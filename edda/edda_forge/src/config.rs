use eyre::{Result, bail};
use serde::Deserialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Deserialize)]
pub struct ForgeConfig {
    pub container: ContainerConfig,
    pub project: ProjectConfig,
    pub steps: StepsConfig,
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
}

#[derive(Debug, Clone, Deserialize)]
pub struct StepsConfig {
    pub write_tests: bool,
    pub validate: Vec<ValidateStep>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ValidateStep {
    pub name: String,
    pub command: String,
    pub retry_on_fail: RetryTarget,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RetryTarget {
    WriteTests,
    WriteCode,
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
            },
            steps: StepsConfig {
                write_tests: true,
                validate: vec![
                    ValidateStep {
                        name: "check".into(),
                        command: "cargo check 2>&1".into(),
                        retry_on_fail: RetryTarget::WriteTests,
                    },
                    ValidateStep {
                        name: "test".into(),
                        command: "cargo test 2>&1".into(),
                        retry_on_fail: RetryTarget::WriteCode,
                    },
                    ValidateStep {
                        name: "bench".into(),
                        command: "cargo bench 2>&1".into(),
                        retry_on_fail: RetryTarget::WriteCode,
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
        Ok(())
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
