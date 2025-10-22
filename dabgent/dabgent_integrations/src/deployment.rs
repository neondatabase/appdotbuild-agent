use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::process::Command;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Status {
    pub message: String,
    pub state: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DeploymentArtifacts {
    pub source_code_path: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Deployment {
    pub create_time: String,
    pub creator: String,
    pub deployment_artifacts: DeploymentArtifacts,
    pub deployment_id: String,
    pub mode: String,
    pub source_code_path: String,
    pub status: Status,
    pub update_time: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AppInfo {
    pub active_deployment: Option<Deployment>,
    pub app_status: Status,
    pub compute_status: Status,
    pub create_time: String,
    pub creator: String,
    pub default_source_code_path: String,
    pub description: String,
    pub effective_budget_policy_id: String,
    pub id: String,
    pub name: String,
    pub oauth2_app_client_id: String,
    pub oauth2_app_integration_id: String,
    pub service_principal_client_id: String,
    pub service_principal_id: i64,
    pub service_principal_name: String,
    pub update_time: String,
    pub updater: String,
    pub url: String,
}

impl AppInfo {
    fn source_path(&self) -> String {
        if self.default_source_code_path.is_empty() {
            return format!("/Workspace/Users/{}/{}/", self.creator, self.name);
        }
        self.default_source_code_path.clone()
    }
}

pub fn get_app_info(app_name: &str) -> Result<AppInfo> {
    let output = Command::new("databricks")
        .args(&["apps", "get", app_name])
        .output()?;

    if !output.status.success() {
        return Err(anyhow::anyhow!(
            "Failed to get app info: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    let json_str = String::from_utf8(output.stdout)?;
    let app_info: AppInfo = serde_json::from_str(&json_str)?;
    Ok(app_info)
}

pub fn create_app(app_name: &str, description: &str) -> Result<AppInfo> {
    let output = Command::new("databricks")
        .args(&["apps", "create", app_name, "--description", description])
        .output()?;

    if !output.status.success() {
        return Err(anyhow::anyhow!(
            "Failed to create app: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    get_app_info(app_name)
}

pub fn sync_workspace(app_info: &AppInfo, source_dir: &str) -> Result<()> {
    let output = Command::new("databricks")
        .args(&["sync", "--include", "public", ".", &app_info.source_path()]) // specific for trpc template
        .current_dir(source_dir)
        .output()?;

    if !output.status.success() {
        return Err(anyhow::anyhow!(
            "Failed to sync workspace: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    Ok(())
}

pub fn deploy_app(app_info: &AppInfo) -> Result<()> {
    let output = Command::new("databricks")
        .args(&[
            "apps",
            "deploy",
            app_info.name.as_str(),
            "--source-code-path",
            &app_info.source_path(),
        ])
        .output()?;

    if !output.status.success() {
        return Err(anyhow::anyhow!(
            "Failed to deploy app: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    Ok(())
}
