use crate::ExecResult;
use dagger_sdk::core::logger::DynLogger;
use dagger_sdk::logging::{StdLogger, TracingLogger};
use eyre::Result;
use std::{io::Write, sync::Arc};

#[derive(Clone)]
pub struct Sandbox {
    ctr: dagger_sdk::Container,
}

impl Sandbox {
    /// Create a sandbox from an existing Dagger container
    pub fn from_container(ctr: dagger_sdk::Container) -> Self {
        Self { ctr }
    }
}

impl crate::Sandbox for Sandbox {
    async fn exec(&mut self, command: &str) -> Result<ExecResult> {
        let ctr = self.ctr.clone();
        let command: Vec<String> = command.split_whitespace().map(String::from).collect();
        let opts = dagger_sdk::ContainerWithExecOptsBuilder::default()
            .expect(dagger_sdk::ReturnType::Any)
            .build()
            .unwrap();
        let ctr = ctr.with_exec_opts(command, opts);
        let res = ExecResult::get_output(&ctr).await?;
        self.ctr = ctr;
        Ok(res)
    }

    async fn write_file(&mut self, path: &str, content: &str) -> Result<()> {
        self.ctr = self.ctr.with_new_file(path, content);
        Ok(())
    }

    async fn read_file(&self, path: &str) -> Result<String> {
        self.ctr.file(path).contents().await.map_err(Into::into)
    }

    async fn delete_file(&mut self, path: &str) -> Result<()> {
        self.ctr = self.ctr.without_file(path);
        Ok(())
    }

    async fn list_directory(&self, path: &str) -> Result<Vec<String>> {
        self.ctr.directory(path).entries().await.map_err(Into::into)
    }
}

impl crate::SandboxFork for Sandbox {
    async fn fork(&self) -> Result<Self>
    where
        Self: Sized,
    {
        let ctr = self.ctr.clone();
        Ok(Sandbox { ctr })
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
