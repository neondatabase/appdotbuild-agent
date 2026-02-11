use dagger_sdk::DaggerConn;
use edda_sandbox::DaggerSandbox;
use eyre::{Result, bail};
use std::path::Path;

pub async fn setup_container(
    client: DaggerConn,
    api_key: &str,
    template_path: &Path,
) -> Result<DaggerSandbox> {
    let template_dir = client
        .host()
        .directory(template_path.to_string_lossy().to_string());

    let install_cmd: Vec<String> = vec![
        "sh".into(),
        "-c".into(),
        "apt-get update && apt-get install -y curl && curl -fsSL https://claude.ai/install.sh | bash".into(),
    ];

    let ctr = client
        .container()
        .from("rust:latest")
        .with_exec(install_cmd)
        .with_env_variable("ANTHROPIC_API_KEY", api_key)
        .with_directory("/app", template_dir)
        .with_workdir("/app");

    let sandbox = DaggerSandbox::from_container(ctr, client);
    Ok(sandbox)
}

/// resolve template path: use provided path or fall back to embedded template
pub fn resolve_template_path(custom_template: Option<&Path>) -> Result<std::path::PathBuf> {
    match custom_template {
        Some(p) => {
            if !p.exists() {
                bail!("template path does not exist: {}", p.display());
            }
            Ok(p.to_path_buf())
        }
        None => {
            // use the embedded template relative to the crate
            let manifest_dir = env!("CARGO_MANIFEST_DIR");
            let template = Path::new(manifest_dir).join("template");
            if !template.exists() {
                bail!(
                    "embedded template not found at {}",
                    template.display()
                );
            }
            Ok(template)
        }
    }
}
