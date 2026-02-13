use crate::config::{AgentBackend, ForgeConfig};
use dagger_sdk::{DaggerConn, HostDirectoryOpts};
use edda_sandbox::DaggerSandbox;
use eyre::Result;
use std::path::Path;

fn sh(cmd: &str) -> Vec<String> {
    vec!["sh".into(), "-c".into(), cmd.into()]
}

pub struct AgentAuth {
    pub api_key: Option<String>,
    /// path to auth.json file (not directory)
    pub opencode_auth_file: Option<String>,
    pub opencode_config_dir: Option<String>,
}

pub async fn setup_container(
    client: DaggerConn,
    auth: &AgentAuth,
    config: &ForgeConfig,
    source_path: &Path,
) -> Result<DaggerSandbox> {
    let exclude_refs: Vec<&str> = config.project.exclude.iter().map(|s| s.as_str()).collect();
    let source_dir = if exclude_refs.is_empty() {
        client
            .host()
            .directory(source_path.to_string_lossy().to_string())
    } else {
        client.host().directory_opts(
            source_path.to_string_lossy().to_string(),
            HostDirectoryOpts {
                exclude: Some(exclude_refs),
                include: None,
                no_cache: None,
                gitignore: None,
            },
        )
    };

    let mut ctr = client.container().from(&config.container.image);

    // run setup commands (as root)
    for cmd in &config.container.setup {
        ctr = ctr.with_exec(sh(cmd));
    }

    // create user
    ctr = ctr.with_exec(sh(&config.container.user_setup));

    // mount source and chown to user (still running as root)
    let user = &config.container.user;
    let workdir = &config.project.workdir;
    ctr = ctr
        .with_directory(workdir, source_dir)
        .with_exec(sh(&format!("chown -R {user}:{user} {workdir}")));

    let home = format!("/home/{user}");

    // mount opencode auth/config before switching to user (needs root for chown)
    if matches!(&config.agent.backend, AgentBackend::OpenCode) {
        if let Some(auth_file) = &auth.opencode_auth_file {
            let target = format!("{home}/.local/share/opencode/auth.json");
            let host_file = client.host().file(auth_file);
            ctr = ctr.with_file(&target, host_file);
        }
        if let Some(config_dir) = &auth.opencode_config_dir {
            let target = format!("{home}/.config/opencode");
            let host_dir = client.host().directory(config_dir);
            ctr = ctr.with_directory(&target, host_dir);
        }
        // chown the whole user home to fix ownership of mounted files
        ctr = ctr.with_exec(sh(&format!("chown -R {user}:{user} {home}")));
    }

    // switch to user
    ctr = ctr.with_user(user);

    // set env vars
    for (key, value) in &config.container.env {
        ctr = ctr.with_env_variable(key, value);
    }

    // forward API key if available
    if let Some(key) = &auth.api_key {
        ctr = ctr.with_env_variable("ANTHROPIC_API_KEY", key);
    }

    // install agent CLI and configure
    match &config.agent.backend {
        AgentBackend::Claude => {
            ctr = ctr.with_exec(sh("curl -fsSL https://claude.ai/install.sh | bash"));
        }
        AgentBackend::OpenCode => {
            ctr = ctr.with_exec(sh(
                "curl -fsSL https://opencode.ai/install | bash",
            ));
            // symlink into a standard PATH location since Dagger doesn't expand $PATH
            ctr = ctr.with_exec(sh(&format!(
                "sudo ln -sf {home}/.opencode/bin/opencode /usr/local/bin/opencode"
            )));
            // write per-project config to auto-approve all permissions
            ctr = ctr.with_exec(sh(&format!(
                "mkdir -p {workdir} && echo '{{\"permission\":\"allow\"}}' > {workdir}/opencode.json"
            )));
        }
    }

    ctr = ctr.with_workdir(workdir);

    let sandbox = DaggerSandbox::from_container(ctr, client);
    Ok(sandbox)
}
