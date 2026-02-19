use crate::config::{AgentBackend, ForgeConfig, MountConfig};
use crate::container::AgentAuth;
use edda_sandbox::{ExecResult, Sandbox};
use eyre::{Result, bail};
use globset::{GlobSet, GlobSetBuilder};
use std::collections::HashMap;
use std::path::{Component, Path, PathBuf};
use tokio::process::Command;
use tracing::{info, warn};

pub struct LocalRun {
    pub sandbox: LocalSandbox,
    _workspace: tempfile::TempDir,
}

#[derive(Clone, Debug)]
pub struct LocalSandbox {
    root: PathBuf,
    workdir: PathBuf,
    env: HashMap<String, String>,
}

impl LocalSandbox {
    fn resolve_path(&self, path: &str) -> Result<PathBuf> {
        let input = Path::new(path);
        let target = if input.is_absolute() {
            self.root.join(normalize_components(input)?)
        } else {
            self.workdir.join(normalize_components(input)?)
        };
        Ok(target)
    }
}

impl Sandbox for LocalSandbox {
    async fn exec(&mut self, command: &str) -> Result<ExecResult> {
        let mut cmd = Command::new("sh");
        cmd.arg("-c").arg(command).current_dir(&self.workdir);
        for (k, v) in &self.env {
            cmd.env(k, v);
        }
        // own process group so kill_on_drop takes the whole child tree
        cmd.process_group(0);
        cmd.kill_on_drop(true);

        let child = cmd.spawn()?;
        let output = child.wait_with_output().await?;
        Ok(ExecResult {
            exit_code: output.status.code().unwrap_or(-1) as isize,
            stdout: String::from_utf8_lossy(&output.stdout).to_string(),
            stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        })
    }

    async fn write_file(&mut self, path: &str, content: &str) -> Result<()> {
        let target = self.resolve_path(path)?;
        if let Some(parent) = target.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        tokio::fs::write(target, content).await?;
        Ok(())
    }

    async fn write_files(&mut self, files: Vec<(&str, &str)>) -> Result<()> {
        for (path, content) in files {
            self.write_file(path, content).await?;
        }
        Ok(())
    }

    async fn read_file(&self, path: &str) -> Result<String> {
        let target = self.resolve_path(path)?;
        let content = tokio::fs::read_to_string(target).await?;
        Ok(content)
    }

    async fn delete_file(&mut self, path: &str) -> Result<()> {
        let target = self.resolve_path(path)?;
        match tokio::fs::metadata(&target).await {
            Ok(meta) if meta.is_dir() => {
                tokio::fs::remove_dir_all(target).await?;
            }
            Ok(_) => {
                tokio::fs::remove_file(target).await?;
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.into()),
        }
        Ok(())
    }

    async fn list_directory(&self, path: &str) -> Result<Vec<String>> {
        let target = self.resolve_path(path)?;
        let mut entries = tokio::fs::read_dir(target).await?;
        let mut out = Vec::new();
        while let Some(entry) = entries.next_entry().await? {
            out.push(entry.file_name().to_string_lossy().to_string());
        }
        out.sort();
        Ok(out)
    }

    async fn set_workdir(&mut self, path: &str) -> Result<()> {
        let target = self.resolve_path(path)?;
        tokio::fs::create_dir_all(&target).await?;
        self.workdir = target;
        Ok(())
    }

    async fn export_directory(&self, container_path: &str, host_path: &str) -> Result<String> {
        let source = self.resolve_path(container_path)?;
        let target = PathBuf::from(host_path);
        if target.exists() {
            std::fs::remove_dir_all(&target)?;
        }
        std::fs::create_dir_all(&target)?;
        copy_tree(&source, &target)?;
        Ok(target.to_string_lossy().to_string())
    }
}

pub fn setup_local_sandbox(
    auth: &AgentAuth,
    config: &ForgeConfig,
    source_path: &Path,
    config_dir: &Path,
) -> Result<LocalRun> {
    let workspace = tempfile::tempdir()?;
    let root = workspace.path().to_path_buf();

    let workdir_rel = normalize_workdir(&config.project.workdir)?;
    let workdir = root.join(&workdir_rel);
    std::fs::create_dir_all(&workdir)?;

    let matcher = build_exclude_matcher(&config.project.exclude)?;
    copy_dir_with_excludes(source_path, &workdir, source_path, &matcher)?;

    for mount in &config.mounts {
        let host_path = mount.resolve_host_path(config_dir)?;
        let target = resolve_local_mount_target(mount, &workdir_rel, &workdir, &host_path)?;

        if host_path.is_file() {
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::copy(&host_path, &target)?;
        } else {
            std::fs::create_dir_all(&target)?;
            copy_tree(&host_path, &target)?;
        }
        info!(
            host = %host_path.display(),
            container = %mount.container,
            local_target = %target.display(),
            "mounted local path"
        );
    }

    if !config.container.setup.is_empty() || !config.container.user_setup.is_empty() {
        warn!("local runtime ignores [container] setup/user directives");
    }
    if !config.container.env.is_empty() {
        warn!("local runtime ignores [container.env]; use host environment variables instead");
    }

    let mut env = HashMap::new();
    if let Some(key) = &auth.api_key {
        env.insert("ANTHROPIC_API_KEY".to_string(), key.clone());
    }

    if matches!(config.agent.backend, AgentBackend::OpenCode) {
        info!("using host OpenCode auth/config in local runtime");
    }

    Ok(LocalRun {
        sandbox: LocalSandbox { root, workdir, env },
        _workspace: workspace,
    })
}

fn resolve_local_mount_target(
    mount: &MountConfig,
    workdir_rel: &Path,
    workdir: &Path,
    host_path: &Path,
) -> Result<PathBuf> {
    if let Some(local_rel) = mount.resolve_local_target()? {
        return if local_rel.as_os_str().is_empty() {
            if host_path.is_file() {
                bail!(
                    "mount '{}' uses local_target='.' with a file host path; provide a file path",
                    mount.host
                );
            }
            Ok(workdir.to_path_buf())
        } else {
            Ok(workdir.join(local_rel))
        };
    }

    let container_rel = normalize_workdir(&mount.container)?;
    let relative = container_rel.strip_prefix(workdir_rel).map_err(|_| {
        eyre::eyre!(
            "local runtime mount '{}' -> '{}' is outside project.workdir '{}'; \
             set mounts.local_target to place it under the local workspace",
            mount.host,
            mount.container,
            format!("/{}", workdir_rel.display())
        )
    })?;

    if relative.as_os_str().is_empty() {
        if host_path.is_file() {
            bail!(
                "mount '{}' targets workdir root in local runtime; set mounts.local_target",
                mount.container
            );
        }
        Ok(workdir.to_path_buf())
    } else {
        Ok(workdir.join(relative))
    }
}

fn build_exclude_matcher(patterns: &[String]) -> Result<GlobSet> {
    let mut builder = GlobSetBuilder::new();
    for pattern in patterns {
        builder.add(globset::Glob::new(pattern)?);
    }
    Ok(builder.build()?)
}

fn copy_dir_with_excludes(
    source: &Path,
    target: &Path,
    source_root: &Path,
    matcher: &GlobSet,
) -> Result<()> {
    std::fs::create_dir_all(target)?;
    for entry in std::fs::read_dir(source)? {
        let entry = entry?;
        let src_path = entry.path();
        let rel = src_path.strip_prefix(source_root)?;
        let rel_norm = rel.to_string_lossy().replace('\\', "/");
        if matcher.is_match(&rel_norm) {
            continue;
        }

        let dst_path = target.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir_with_excludes(&src_path, &dst_path, source_root, matcher)?;
        } else if entry.file_type()?.is_file() {
            if let Some(parent) = dst_path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::copy(&src_path, &dst_path)?;
        }
    }
    Ok(())
}

fn copy_tree(source: &Path, target: &Path) -> Result<()> {
    if source.is_file() {
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::copy(source, target)?;
        return Ok(());
    }

    std::fs::create_dir_all(target)?;
    for entry in std::fs::read_dir(source)? {
        let entry = entry?;
        let src = entry.path();
        let dst = target.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_tree(&src, &dst)?;
        } else if entry.file_type()?.is_file() {
            if let Some(parent) = dst.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::copy(src, dst)?;
        }
    }
    Ok(())
}

fn normalize_workdir(path: &str) -> Result<PathBuf> {
    if path.is_empty() {
        bail!("path must not be empty");
    }
    normalize_components(Path::new(path))
}

fn normalize_components(path: &Path) -> Result<PathBuf> {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Prefix(_) => bail!("windows paths are not supported"),
            Component::RootDir | Component::CurDir => {}
            Component::Normal(segment) => out.push(segment),
            Component::ParentDir => bail!("path traversal is not allowed: {}", path.display()),
        }
    }
    Ok(out)
}
