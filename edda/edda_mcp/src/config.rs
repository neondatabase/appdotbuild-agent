use crate::providers::ProviderType;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(default)]
pub struct Config {
    pub allow_deployment: bool,
    pub required_providers: Vec<ProviderType>,
}

impl Config {
    pub fn load_from_dir() -> Self {
        let default_config = Self::default();
        let home_dir = match std::env::var("HOME") {
            Ok(dir) => dir,
            Err(_) => return default_config,
        };

        let config_path = format!("{}/.edda/config.json", home_dir);
        let contents = match std::fs::read_to_string(&config_path) {
            Ok(contents) => contents,
            Err(_) => return default_config,
        };

        match serde_json::from_str::<Config>(&contents) {
            Ok(config) => config,
            Err(_) => default_config,
        }
    }
}

impl Default for Config {
    fn default() -> Self {
        Self {
            allow_deployment: true,
            required_providers: vec![
                ProviderType::Databricks,
                ProviderType::Deployment,
                ProviderType::Io,
            ],
        }
    }
}
