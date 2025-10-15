pub mod dagger;
pub mod manager;
pub mod noop;

pub use dagger::Sandbox as DaggerSandbox;
use eyre::Result;
pub use manager::SandboxHandle;
pub use noop::NoOpSandbox;
use serde::{Deserialize, Serialize};
use std::pin::Pin;

pub type FutureBoxed<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ExecResult {
    pub exit_code: isize,
    pub stdout: String,
    pub stderr: String,
}

pub trait Sandbox {
    fn exec(&mut self, command: &str) -> impl Future<Output = Result<ExecResult>> + Send;
    fn write_file(&mut self, path: &str, content: &str) -> impl Future<Output = Result<()>> + Send;
    fn write_files(&mut self, files: Vec<(&str, &str)>) -> impl Future<Output = Result<()>> + Send;
    fn read_file(&self, path: &str) -> impl Future<Output = Result<String>> + Send;
    fn delete_file(&mut self, path: &str) -> impl Future<Output = Result<()>> + Send;
    fn list_directory(&self, path: &str) -> impl Future<Output = Result<Vec<String>>> + Send;
    fn set_workdir(&mut self, path: &str) -> impl Future<Output = Result<()>> + Send;
    fn export_directory(
        &self,
        container_path: &str,
        host_path: &str,
    ) -> impl Future<Output = Result<String>> + Send;

    fn refresh_from_host(
        &mut self,
        host_path: &str,
        container_path: &str,
    ) -> impl Future<Output = Result<()>> + Send {
        async move {
            let _ = (host_path, container_path);
            Err(eyre::eyre!("refresh_from_host not supported"))
        }
    }

    fn fork(&self) -> impl Future<Output = Result<Self>> + Send
    where
        Self: Sized,
    {
        async { Err(eyre::eyre!("Fork not supported")) }
    }

    fn boxed(self) -> Box<dyn SandboxDyn>
    where
        Self: Sized + Send + Sync + 'static,
    {
        Box::new(self)
    }
}

pub trait SandboxDyn: Send + Sync {
    fn exec<'a>(&'a mut self, command: &'a str) -> FutureBoxed<'a, Result<ExecResult>>;
    fn write_file<'a>(&'a mut self, path: &'a str, content: &'a str)
    -> FutureBoxed<'a, Result<()>>;
    fn write_files<'a>(&'a mut self, files: Vec<(&'a str, &'a str)>)
    -> FutureBoxed<'a, Result<()>>;
    fn read_file<'a>(&'a self, path: &'a str) -> FutureBoxed<'a, Result<String>>;
    fn delete_file<'a>(&'a mut self, path: &'a str) -> FutureBoxed<'a, Result<()>>;
    fn list_directory<'a>(&'a self, path: &'a str) -> FutureBoxed<'a, Result<Vec<String>>>;
    fn set_workdir<'a>(&'a mut self, path: &'a str) -> FutureBoxed<'a, Result<()>>;
    fn export_directory<'a>(
        &'a self,
        container_path: &'a str,
        host_path: &'a str,
    ) -> FutureBoxed<'a, Result<String>>;
    fn refresh_from_host<'a>(
        &'a mut self,
        host_path: &'a str,
        container_path: &'a str,
    ) -> FutureBoxed<'a, Result<()>>;
    fn fork(&self) -> FutureBoxed<'_, Result<Box<dyn SandboxDyn>>>;
}

impl<T: Sandbox + Send + Sync + 'static> SandboxDyn for T {
    fn exec<'a>(&'a mut self, command: &'a str) -> FutureBoxed<'a, Result<ExecResult>> {
        Box::pin(self.exec(command))
    }

    fn write_file<'a>(
        &'a mut self,
        path: &'a str,
        content: &'a str,
    ) -> FutureBoxed<'a, Result<()>> {
        Box::pin(self.write_file(path, content))
    }

    fn write_files<'a>(
        &'a mut self,
        files: Vec<(&'a str, &'a str)>,
    ) -> FutureBoxed<'a, Result<()>> {
        Box::pin(self.write_files(files))
    }

    fn read_file<'a>(&'a self, path: &'a str) -> FutureBoxed<'a, Result<String>> {
        Box::pin(self.read_file(path))
    }

    fn delete_file<'a>(&'a mut self, path: &'a str) -> FutureBoxed<'a, Result<()>> {
        Box::pin(self.delete_file(path))
    }

    fn list_directory<'a>(&'a self, path: &'a str) -> FutureBoxed<'a, Result<Vec<String>>> {
        Box::pin(self.list_directory(path))
    }

    fn set_workdir<'a>(&'a mut self, path: &'a str) -> FutureBoxed<'a, Result<()>> {
        Box::pin(self.set_workdir(path))
    }

    fn export_directory<'a>(
        &'a self,
        container_path: &'a str,
        host_path: &'a str,
    ) -> FutureBoxed<'a, Result<String>> {
        Box::pin(self.export_directory(container_path, host_path))
    }

    fn refresh_from_host<'a>(
        &'a mut self,
        host_path: &'a str,
        container_path: &'a str,
    ) -> FutureBoxed<'a, Result<()>> {
        Box::pin(self.refresh_from_host(host_path, container_path))
    }

    fn fork(&self) -> FutureBoxed<'_, Result<Box<dyn SandboxDyn>>> {
        Box::pin(async move { self.fork().await.map(|fork| fork.boxed()) })
    }
}
