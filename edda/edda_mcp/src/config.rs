use crate::providers::ProviderType;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(default)]
pub struct Config {
    pub allow_deployment: bool,
    pub required_providers: Vec<ProviderType>,
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
