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

    let install_deps: Vec<String> = vec![
        "sh".into(),
        "-c".into(),
        "apt-get update && apt-get install -y curl sudo".into(),
    ];

    let create_user: Vec<String> = vec![
        "sh".into(),
        "-c".into(),
        "useradd -m -s /bin/bash forge && echo 'forge ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers && cp -r /usr/local/cargo /home/forge/.cargo && cp -r /usr/local/rustup /home/forge/.rustup && chown -R forge:forge /home/forge/.cargo /home/forge/.rustup".into(),
    ];

    let install_claude: Vec<String> = vec![
        "sh".into(),
        "-c".into(),
        "curl -fsSL https://claude.ai/install.sh | bash".into(),
    ];

    let ctr = client
        .container()
        .from("rust:latest")
        .with_exec(install_deps)
        .with_exec(create_user)
        .with_user("forge")
        .with_env_variable("PATH", "/home/forge/.local/bin:/home/forge/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
        .with_env_variable("CARGO_HOME", "/home/forge/.cargo")
        .with_env_variable("RUSTUP_HOME", "/home/forge/.rustup")
        .with_exec(install_claude)
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
