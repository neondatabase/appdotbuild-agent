use crate::ExecResult;
use dagger_sdk::core::logger::DynLogger;
use dagger_sdk::logging::{StdLogger, TracingLogger};
use eyre::Result;
use globset::{GlobSet, GlobSetBuilder};
use std::{future::Future, io::Write, sync::Arc};

/// Max number of chained Dagger operations before auto-syncing.
/// Dagger's GraphQL query depth limit is ~120; we sync well before that.
const AUTO_SYNC_THRESHOLD: usize = 80;

#[derive(Clone)]
pub struct Sandbox {
    ctr: dagger_sdk::Container,
    client: dagger_sdk::DaggerConn,
    restricted_files: GlobSet,
    /// Tracks chained operations since last sync to avoid hitting Dagger query depth limits.
    ops_since_sync: usize,
}

impl Sandbox {
    /// Create a sandbox from an existing Dagger container and client
    pub fn from_container(ctr: dagger_sdk::Container, client: dagger_sdk::DaggerConn) -> Self {
        Self {
            ctr,
            client,
            restricted_files: GlobSet::empty(),
            ops_since_sync: 0,
        }
    }

    /// Add file restrictions to the sandbox
    pub fn with_restrictions(mut self, patterns: Vec<String>) -> Result<Self> {
        let mut builder = GlobSetBuilder::new();
        for pattern in patterns {
            builder.add(globset::Glob::new(&pattern)?);
        }
        self.restricted_files = builder.build()?;
        Ok(self)
    }

    /// Check if a file path matches any restricted patterns
    fn is_restricted(&self, path: &str) -> bool {
        let normalized = path.strip_prefix('/').unwrap_or(path);
        self.restricted_files.is_match(normalized)
    }

    /// Get the cloned underlying Dagger container
    pub fn container(&self) -> dagger_sdk::Container {
        self.ctr.clone()
    }

    /// Flatten the Dagger query chain by syncing the container and reloading from its ID.
    ///
    /// Dagger builds a nested GraphQL query for every chained operation (exec, write_file, etc.).
    /// After ~120 operations the query exceeds engine limits. Calling sync() materialises the
    /// current container state and replaces the internal reference with a fresh one that has a
    /// depth-1 query, allowing further operations to proceed.
    pub async fn sync(&mut self) -> Result<()> {
        let id = self.ctr.sync().await.map_err(|e| eyre::eyre!("sync: {e}"))?;
        self.ctr = self.client.load_container_from_id(id);
        self.ops_since_sync = 0;
        Ok(())
    }

    /// Sync if we're approaching the Dagger query depth limit.
    async fn auto_sync_if_needed(&mut self) -> Result<()> {
        if self.ops_since_sync >= AUTO_SYNC_THRESHOLD {
            tracing::debug!(ops = self.ops_since_sync, "auto-syncing container to flatten query chain");
            self.sync().await?;
        }
        Ok(())
    }
}

impl crate::Sandbox for Sandbox {
    async fn exec(&mut self, command: &str) -> Result<ExecResult> {
        self.auto_sync_if_needed().await?;
        let ctr = self.ctr.clone();
        let command = vec!["sh".to_string(), "-c".to_string(), command.to_string()];
        let opts = dagger_sdk::ContainerWithExecOptsBuilder::default()
            .expect(dagger_sdk::ReturnType::Any)
            .build()
            .unwrap();
        let ctr = ctr.with_exec_opts(command, opts);
        let res = ExecResult::get_output(&ctr).await?;
        self.ctr = ctr;
        self.ops_since_sync += 1;
        Ok(res)
    }

    async fn write_file(&mut self, path: &str, content: &str) -> Result<()> {
        if self.is_restricted(path) {
            return Err(eyre::eyre!(
                "File '{}' is protected and cannot be modified",
                path
            ));
        }
        self.auto_sync_if_needed().await?;
        self.ctr = self.ctr.with_new_file(path, content);
        self.ops_since_sync += 1;
        Ok(())
    }

    /// Write multiple files to the container in a single operation to prevent deep query chains.
    /// This is much more efficient than individual write_file calls for bulk operations.
    async fn write_files(&mut self, files: Vec<(&str, &str)>) -> Result<()> {
        if files.is_empty() {
            return Ok(());
        }

        // Check for restricted files first
        for (file_path, _) in &files {
            if self.is_restricted(file_path) {
                return Err(eyre::eyre!(
                    "File '{}' is protected and cannot be modified",
                    file_path
                ));
            }
        }

        // Create a temporary directory to stage all files
        let temp_dir = tempfile::tempdir()?;
        let temp_path = temp_dir.path();

        // Write all files to the temporary directory
        for (file_path, contents) in &files {
            let full_path = temp_path.join(file_path.strip_prefix('/').unwrap_or(file_path));

            // Create parent directories if needed
            if let Some(parent) = full_path.parent() {
                std::fs::create_dir_all(parent)?;
            }

            std::fs::write(&full_path, contents)?;
        }

        // Use with_directory to add all files at once - this prevents deep query chains
        let host_dir = self
            .client
            .host()
            .directory(temp_path.to_string_lossy().to_string());

        // Mount the entire temporary directory to root, which will merge all files
        self.ctr = self.ctr.with_directory("/", host_dir);

        // Force evaluation and flatten the query chain
        self.sync().await?;

        Ok(())
    }

    async fn read_file(&self, path: &str) -> Result<String> {
        self.ctr.file(path).contents().await.map_err(Into::into)
    }

    async fn delete_file(&mut self, path: &str) -> Result<()> {
        if self.is_restricted(path) {
            return Err(eyre::eyre!(
                "File '{}' is protected and cannot be modified",
                path
            ));
        }
        self.ctr = self.ctr.without_file(path);
        self.ops_since_sync += 1;
        Ok(())
    }

    async fn list_directory(&self, path: &str) -> Result<Vec<String>> {
        self.ctr.directory(path).entries().await.map_err(Into::into)
    }

    async fn set_workdir(&mut self, path: &str) -> Result<()> {
        self.ctr = self.ctr.with_workdir(path);
        self.ops_since_sync += 1;
        Ok(())
    }

    async fn export_directory(&self, container_path: &str, host_path: &str) -> Result<String> {
        let dir = self.ctr.directory(container_path);
        dir.export(host_path).await.map_err(Into::into)
    }

    async fn refresh_from_host(&mut self, host_path: &str, container_path: &str) -> Result<()> {
        let host_dir = self.client.host().directory(host_path.to_string());
        self.ctr = self.ctr.with_directory(container_path, host_dir);
        self.ops_since_sync += 1;
        Ok(())
    }

    async fn fork(&self) -> Result<Self>
    where
        Self: Sized,
    {
        let ctr = self.ctr.clone();
        let client = self.client.clone();
        let restricted_files = self.restricted_files.clone();
        Ok(Sandbox {
            ctr,
            client,
            restricted_files,
            ops_since_sync: self.ops_since_sync,
        })
    }
}

impl ExecResult {
    async fn get_output(ctr: &dagger_sdk::Container) -> Result<Self> {
        Ok(Self {
            exit_code: ctr.exit_code().await?,
            stdout: ctr.stdout().await?,
            stderr: ctr.stderr().await?,
        })
    }
}

pub enum Logger {
    Default,
    Tracing,
    Silent,
    /// directory path to save dagger logs to
    File(String),
}

pub struct ConnectOpts {
    pub logger: Logger,
    pub execute_timeout_secs: Option<u64>,
}

impl ConnectOpts {
    pub fn new(logger: Logger, execute_timeout_secs: Option<u64>) -> Self {
        Self {
            logger,
            execute_timeout_secs,
        }
    }

    pub fn with_logger(mut self, logger: Logger) -> Self {
        self.logger = logger;
        self
    }

    pub fn with_execute_timeout(mut self, execute_timeout_secs: Option<u64>) -> Self {
        self.execute_timeout_secs = execute_timeout_secs;
        self
    }

    pub async fn connect<F, Fut>(self, dagger: F) -> Result<(), dagger_sdk::errors::ConnectError>
    where
        F: FnOnce(dagger_sdk::DaggerConn) -> Fut + 'static,
        Fut: Future<Output = eyre::Result<()>> + 'static,
    {
        let logger = match self.logger {
            Logger::Default => {
                let logger: DynLogger = Arc::new(StdLogger::default());
                Some(logger)
            }
            Logger::Tracing => {
                let logger: DynLogger = Arc::new(TracingLogger::default());
                Some(logger)
            }
            Logger::File(path) => {
                let logger = FileLogger::new(path);
                let logger: dagger_sdk::core::logger::DynLogger = Arc::new(logger);
                Some(logger)
            }
            Logger::Silent => None,
        };
        let config = dagger_sdk::Config {
            logger,
            execute_timeout_ms: self.execute_timeout_secs.map(|secs| secs * 1000),
            ..Default::default()
        };
        dagger_sdk::connect_opts(config, dagger).await
    }
}

pub struct FileLogger {
    directory: String,
}

impl FileLogger {
    pub fn new(directory: String) -> Self {
        std::fs::create_dir_all(&directory).unwrap();
        Self { directory }
    }

    fn open(&self, path: &str) -> eyre::Result<std::fs::File> {
        const PREFIX: &str = "dagger";
        let path = format!("{}/{}_{}", self.directory, PREFIX, path);
        std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .map_err(Into::into)
    }
}

impl dagger_sdk::core::logger::Logger for FileLogger {
    fn stdout(&self, output: &str) -> eyre::Result<()> {
        let mut file = self.open("stdout.log")?;
        file.write_all(output.as_bytes())?;
        Ok(())
    }

    fn stderr(&self, output: &str) -> eyre::Result<()> {
        let mut file = self.open("stderr.log")?;
        file.write_all(output.as_bytes())?;
        Ok(())
    }
}

impl Default for ConnectOpts {
    fn default() -> Self {
        Self {
            logger: Logger::Silent,
            execute_timeout_secs: Some(300),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_restricted_exact_match() {
        let matcher = build_restriction_matcher(vec!["config.yaml".to_string()]).unwrap();

        assert!(is_path_restricted(&matcher, "config.yaml"));
        assert!(is_path_restricted(&matcher, "/config.yaml"));
        assert!(!is_path_restricted(&matcher, "other.yaml"));
    }

    #[test]
    fn test_is_restricted_wildcard() {
        let matcher = build_restriction_matcher(vec!["*.env".to_string()]).unwrap();

        assert!(is_path_restricted(&matcher, ".env"));
        assert!(is_path_restricted(&matcher, "prod.env"));
        assert!(is_path_restricted(&matcher, "/app/.env"));
        assert!(!is_path_restricted(&matcher, "env.txt"));
    }

    #[test]
    fn test_is_restricted_directory_pattern() {
        let matcher = build_restriction_matcher(vec!["secrets/**".to_string()]).unwrap();

        assert!(is_path_restricted(&matcher, "secrets/api.key"));
        assert!(is_path_restricted(&matcher, "/secrets/db/password.txt"));
        assert!(!is_path_restricted(&matcher, "other/file.txt"));
    }

    #[test]
    fn test_is_restricted_multiple_patterns() {
        let matcher = build_restriction_matcher(vec![
            "*.env".to_string(),
            "secrets/**".to_string(),
            "config.yaml".to_string(),
        ])
        .unwrap();

        assert!(is_path_restricted(&matcher, ".env"));
        assert!(is_path_restricted(&matcher, "secrets/key.pem"));
        assert!(is_path_restricted(&matcher, "config.yaml"));
        assert!(!is_path_restricted(&matcher, "app.py"));
    }

    #[test]
    fn test_empty_restrictions() {
        let matcher = build_restriction_matcher(vec![]).unwrap();

        assert!(!is_path_restricted(&matcher, "any/file.txt"));
        assert!(!is_path_restricted(&matcher, ".env"));
    }

    fn build_restriction_matcher(patterns: Vec<String>) -> Result<GlobSet> {
        let mut builder = GlobSetBuilder::new();
        for pattern in patterns {
            builder.add(globset::Glob::new(&pattern)?);
        }
        builder.build().map_err(Into::into)
    }

    fn is_path_restricted(matcher: &GlobSet, path: &str) -> bool {
        let normalized = path.strip_prefix('/').unwrap_or(path);
        matcher.is_match(normalized)
    }
}
