use crate::config::ForgeConfig;
use dagger_sdk::{DaggerConn, HostDirectoryOpts};
use edda_sandbox::DaggerSandbox;
use eyre::Result;
use std::path::Path;

fn sh(cmd: &str) -> Vec<String> {
    vec!["sh".into(), "-c".into(), cmd.into()]
}

pub async fn setup_container(
    client: DaggerConn,
    api_key: &str,
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

    // switch to user
    ctr = ctr.with_user(user);

    // set env vars
    for (key, value) in &config.container.env {
        ctr = ctr.with_env_variable(key, value);
    }

    // install claude CLI (always needed)
    ctr = ctr.with_exec(sh("curl -fsSL https://claude.ai/install.sh | bash"));

    // set API key and workdir
    ctr = ctr
        .with_env_variable("ANTHROPIC_API_KEY", api_key)
        .with_workdir(workdir);

    let sandbox = DaggerSandbox::from_container(ctr, client);
    Ok(sandbox)
}
