use crate::providers::ProviderType;
use serde::{Deserialize, Serialize};

/// Trait that all config types must implement to support CLI overrides.
/// Ensures consistency when adding new config fields.
pub trait ConfigOverride: Sized + Default {
    /// Override struct type containing optional fields
    type Override;

    /// Apply override to this config, consuming both
    fn apply_override(self, override_val: Self::Override) -> Self;
}

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

// Override structs - mirror config structs with all Option<T> fields

#[derive(Default)]
pub struct ConfigOverrides {
    pub with_deployment: Option<bool>,
    pub with_workspace_tools: Option<bool>,
    pub io_config: Option<IoConfigOverrides>,
}

#[derive(Default)]
pub struct IoConfigOverrides {
    pub template: Option<TemplateConfig>,
    pub validation: Option<ValidationConfigOverrides>,
    pub screenshot: Option<ScreenshotConfigOverrides>,
}

#[derive(Default)]
pub struct ValidationConfigOverrides {
    pub command: Option<String>,
    pub docker_image: Option<String>,
}

#[derive(Default)]
pub struct ScreenshotConfigOverrides {
    pub enabled: Option<bool>,
    pub url: Option<String>,
    pub port: Option<u16>,
    pub wait_time_ms: Option<u64>,
}

impl Config {
    pub fn load_from_dir() -> eyre::Result<Self> {
        let edda_dir = match crate::paths::edda_dir() {
            Ok(dir) => dir,
            Err(_) => return Ok(Self::default()),
        };

        let config_path = edda_dir.join("config.json");
        if !config_path.exists() {
            let json = serde_json::to_string_pretty(&Self::default())?;
            std::fs::create_dir_all(&edda_dir)?;
            std::fs::write(&config_path, json)?;
        }

        let contents = std::fs::read_to_string(&config_path)?;
        serde_json::from_str::<Config>(&contents).map_err(Into::into)
    }

}

impl Default for Config {
    fn default() -> Self {
        Self {
            with_deployment: true,
            with_workspace_tools: false,
            required_providers: vec![
                ProviderType::DatabricksRest,
                ProviderType::Deployment,
                ProviderType::Io,
            ],
            io_config: Some(IoConfig::default()),
        }
    }
}

impl Default for IoConfig {
    fn default() -> Self {
        Self {
            template: TemplateConfig::Trpc,
            validation: None,
            screenshot: Some(ScreenshotConfig::default()),
        }
    }
}

impl Default for ValidationConfig {
    fn default() -> Self {
        Self {
            command: String::new(),
            docker_image: String::new(),
        }
    }
}

impl Default for ScreenshotConfig {
    fn default() -> Self {
        Self {
            enabled: Some(true),
            url: Some("/".to_string()),
            port: Some(8000),
            wait_time_ms: Some(30000),
        }
    }
}

// ConfigOverride trait implementations

impl ConfigOverride for Config {
    type Override = ConfigOverrides;

    fn apply_override(mut self, override_val: Self::Override) -> Self {
        if let Some(v) = override_val.with_deployment {
            self.with_deployment = v;
        }
        if let Some(v) = override_val.with_workspace_tools {
            self.with_workspace_tools = v;
        }
        if let Some(io_override) = override_val.io_config {
            self.io_config = Some(
                self.io_config
                    .unwrap_or_default()
                    .apply_override(io_override),
            );
        }
        self
    }
}

impl ConfigOverride for IoConfig {
    type Override = IoConfigOverrides;

    fn apply_override(mut self, override_val: Self::Override) -> Self {
        if let Some(template) = override_val.template {
            self.template = template;
        }
        if let Some(validation_override) = override_val.validation {
            self.validation = Some(
                self.validation
                    .unwrap_or_default()
                    .apply_override(validation_override),
            );
        }
        if let Some(screenshot_override) = override_val.screenshot {
            // special case: enabled=false with no other fields means disable screenshot
            if screenshot_override.enabled == Some(false)
                && screenshot_override.url.is_none()
                && screenshot_override.port.is_none()
                && screenshot_override.wait_time_ms.is_none()
            {
                self.screenshot = None;
            } else {
                self.screenshot = Some(
                    self.screenshot
                        .unwrap_or_default()
                        .apply_override(screenshot_override),
                );
            }
        }
        self
    }
}

impl ConfigOverride for ValidationConfig {
    type Override = ValidationConfigOverrides;

    fn apply_override(mut self, override_val: Self::Override) -> Self {
        if let Some(v) = override_val.command {
            self.command = v;
        }
        if let Some(v) = override_val.docker_image {
            self.docker_image = v;
        }
        self
    }
}

impl ConfigOverride for ScreenshotConfig {
    type Override = ScreenshotConfigOverrides;

    fn apply_override(mut self, override_val: Self::Override) -> Self {
        if let Some(v) = override_val.enabled {
            self.enabled = Some(v);
        }
        if let Some(v) = override_val.url {
            self.url = Some(v);
        }
        if let Some(v) = override_val.port {
            self.port = Some(v);
        }
        if let Some(v) = override_val.wait_time_ms {
            self.wait_time_ms = Some(v);
        }
        self
    }
}
