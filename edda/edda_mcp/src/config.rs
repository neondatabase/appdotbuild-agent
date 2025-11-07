use crate::providers::ProviderType;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(default)]
pub struct Config {
    pub with_deployment: bool,
    pub with_workspace_tools: bool,
    pub required_providers: Vec<ProviderType>,
    pub io_config: Option<IoConfig>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub enum TemplateConfig {
    Trpc,
    Custom { name: String, path: String },
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct IoConfig {
    pub template: TemplateConfig,
    pub validation: Option<ValidationConfig>,
    pub screenshot: Option<ScreenshotConfig>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ValidationConfig {
    pub command: String,
    pub docker_image: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ScreenshotConfig {
    pub enabled: Option<bool>,
    pub url: Option<String>,
    pub port: Option<u16>,
    pub wait_time_ms: Option<u64>,
}

pub struct ConfigOverrides {
    pub with_deployment: Option<bool>,
    pub with_workspace_tools: Option<bool>,
    pub screenshot: Option<ScreenshotOverrides>,
}

pub struct ScreenshotOverrides {
    pub enabled: Option<bool>,
    pub url: Option<String>,
    pub port: Option<u16>,
    pub wait_time_ms: Option<u64>,
}

impl Config {
    pub fn load_from_dir() -> eyre::Result<Self> {
        let default_config = Ok(Self::default());
        let home_dir = match std::env::var("HOME") {
            Ok(dir) => dir,
            Err(_) => return default_config,
        };

        let config_path = format!("{}/.edda/config.json", home_dir);
        if !std::path::Path::new(&config_path).exists() {
            let json = serde_json::to_string_pretty(&Self::default())?;
            std::fs::create_dir_all(format!("{}/.edda", home_dir))?;
            std::fs::write(&config_path, json)?;
        }

        let contents = std::fs::read_to_string(&config_path)?;
        serde_json::from_str::<Config>(&contents).map_err(Into::into)
    }

    /// Apply CLI overrides to loaded config - single place for all config merging
    pub fn apply_overrides(mut self, overrides: ConfigOverrides) -> Self {
        // apply top-level overrides
        if let Some(with_deployment) = overrides.with_deployment {
            self.with_deployment = with_deployment;
        }
        if let Some(with_workspace_tools) = overrides.with_workspace_tools {
            self.with_workspace_tools = with_workspace_tools;
        }

        // apply screenshot overrides
        if let Some(screenshot_overrides) = overrides.screenshot {
            if let Some(mut io_config) = self.io_config {
                // if CLI explicitly disables, set to None
                if screenshot_overrides.enabled == Some(false) {
                    io_config.screenshot = None;
                } else {
                    // Get existing config or create default
                    let mut screenshot_cfg = io_config.screenshot.unwrap_or_else(|| ScreenshotConfig {
                        enabled: None,
                        url: None,
                        port: None,
                        wait_time_ms: None,
                    });

                    // apply individual field overrides
                    if let Some(enabled) = screenshot_overrides.enabled {
                        screenshot_cfg.enabled = Some(enabled);
                    }
                    if let Some(url) = screenshot_overrides.url {
                        screenshot_cfg.url = Some(url);
                    }
                    if let Some(port) = screenshot_overrides.port {
                        screenshot_cfg.port = Some(port);
                    }
                    if let Some(wait_time) = screenshot_overrides.wait_time_ms {
                        screenshot_cfg.wait_time_ms = Some(wait_time);
                    }
                    io_config.screenshot = Some(screenshot_cfg);
                }
                self.io_config = Some(io_config);
            }
        }

        self
    }
}

impl Default for Config {
    fn default() -> Self {
        Self {
            with_deployment: true,
            with_workspace_tools: false,
            required_providers: vec![
                ProviderType::Databricks,
                ProviderType::Deployment,
                ProviderType::Io,
            ],
            io_config: Some(IoConfig {
                template: TemplateConfig::Trpc,
                validation: None,
                screenshot: Some(ScreenshotConfig {
                    enabled: Some(true),
                    url: None,
                    port: None,
                    wait_time_ms: None,
                }),
            }),
        }
    }
}
