use crate::dagger::{ConnectOpts, Sandbox as DaggerSandbox};
use eyre::Result;
use std::collections::HashMap;
use tokio::sync::{mpsc, oneshot};

struct SandboxManager {
    receiver: mpsc::Receiver<ManagerMessage>,
    client: dagger_sdk::DaggerConn,
    registry: HashMap<String, DaggerSandbox>,
}

enum ManagerMessage {
    CreateFromDirectory {
        id: String,
        host_dir: String,
        dockerfile: String,
        restricted_files: Vec<String>,
        respond_to: oneshot::Sender<Result<DaggerSandbox>>,
    },
    Get {
        id: String,
        respond_to: oneshot::Sender<Option<DaggerSandbox>>,
    },
    Set {
        id: String,
        sandbox: DaggerSandbox,
        respond_to: oneshot::Sender<()>,
    },
    Shutdown,
}

impl SandboxManager {
    fn new(receiver: mpsc::Receiver<ManagerMessage>, client: dagger_sdk::DaggerConn) -> Self {
        Self {
            receiver,
            client,
            registry: HashMap::new(),
        }
    }

    async fn handle_message(&mut self, msg: ManagerMessage) -> bool {
        match msg {
            ManagerMessage::CreateFromDirectory {
                id,
                host_dir,
                dockerfile,
                restricted_files,
                respond_to,
            } => {
                let result = self.create_sandbox(&id, &host_dir, &dockerfile, restricted_files).await;
                let _ = respond_to.send(result);
                true
            }
            ManagerMessage::Get { id, respond_to } => {
                let sandbox = self.registry.get(&id).cloned();
                let _ = respond_to.send(sandbox);
                true
            }
            ManagerMessage::Set {
                id,
                sandbox,
                respond_to,
            } => {
                self.registry.insert(id, sandbox);
                let _ = respond_to.send(());
                true
            }
            ManagerMessage::Shutdown => false,
        }
    }

    async fn create_sandbox(
        &mut self,
        id: &str,
        host_dir: &str,
        dockerfile: &str,
        restricted_files: Vec<String>,
    ) -> Result<DaggerSandbox> {
        let opts = dagger_sdk::ContainerBuildOptsBuilder::default()
            .dockerfile(dockerfile)
            .build()?;

        let ctr = self
            .client
            .container()
            .build_opts(self.client.host().directory(host_dir), opts);

        ctr.sync().await?;
        let mut sandbox = DaggerSandbox::from_container(ctr, self.client.clone());
        if !restricted_files.is_empty() {
            sandbox = sandbox.with_restrictions(restricted_files)?;
        }
        self.registry.insert(id.to_string(), sandbox.clone());
        Ok(sandbox)
    }
}

async fn run_sandbox_manager(mut manager: SandboxManager) {
    while let Some(msg) = manager.receiver.recv().await {
        if !manager.handle_message(msg).await {
            break;
        }
    }
}

pub struct SandboxHandle {
    sender: mpsc::Sender<ManagerMessage>,
}

impl Clone for SandboxHandle {
    fn clone(&self) -> Self {
        Self {
            sender: self.sender.clone(),
        }
    }
}

impl Drop for SandboxHandle {
    fn drop(&mut self) {
        let sender = self.sender.clone();
        tokio::spawn(async move {
            let _ = sender.send(ManagerMessage::Shutdown).await;
        });
    }
}

impl SandboxHandle {
    pub fn new(opts: ConnectOpts) -> Self {
        let (sender, receiver) = mpsc::channel(32);

        tokio::spawn(async move {
            let _ = opts
                .connect(move |client| async move {
                    let manager = SandboxManager::new(receiver, client);
                    run_sandbox_manager(manager).await;
                    Ok(())
                })
                .await;
        });

        Self { sender }
    }

    pub async fn create_from_directory(
        &self,
        id: &str,
        host_dir: &str,
        dockerfile: &str,
        restricted_files: Vec<String>,
    ) -> Result<DaggerSandbox> {
        let (send, recv) = oneshot::channel();
        let msg = ManagerMessage::CreateFromDirectory {
            id: id.to_owned(),
            host_dir: host_dir.to_owned(),
            dockerfile: dockerfile.to_owned(),
            restricted_files,
            respond_to: send,
        };
        let _ = self.sender.send(msg).await;
        recv_eyre(recv).await?
    }

    pub async fn get(&self, id: &str) -> Result<Option<DaggerSandbox>> {
        let (send, recv) = oneshot::channel();
        let msg = ManagerMessage::Get {
            id: id.to_owned(),
            respond_to: send,
        };
        let _ = self.sender.send(msg).await;
        recv_eyre(recv).await
    }

    pub async fn set(&self, id: &str, sandbox: DaggerSandbox) -> Result<()> {
        let (send, recv) = oneshot::channel();
        let msg = ManagerMessage::Set {
            id: id.to_owned(),
            sandbox,
            respond_to: send,
        };
        let _ = self.sender.send(msg).await;
        recv_eyre(recv).await
    }
}

async fn recv_eyre<T>(recv: oneshot::Receiver<T>) -> Result<T> {
    recv.await
        .map_err(|_| eyre::eyre!("Actor task has been killed"))
}
