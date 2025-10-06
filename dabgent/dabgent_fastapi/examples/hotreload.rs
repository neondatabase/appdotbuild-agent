use dabgent_agent::processor::tools::TemplateConfig;
use dabgent_sandbox::dagger::{ConnectOpts, Logger};
use dabgent_sandbox::{DaggerSandbox, Sandbox, SandboxHandle};
use eyre::Result;
use tokio::signal;

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();
    run_worker().await.unwrap();
}

pub async fn run_worker() -> Result<()> {
    let sandbox_handle = SandboxHandle::new(ConnectOpts::default().with_logger(Logger::Default));
    let template_config = TemplateConfig::new(
        "./dabgent_fastapi".to_string(),
        "fastapi.Dockerfile".to_string(),
    )
    .with_template("../dataapps/template_minimal".to_string());
    let mut sandbox = sandbox_handle
        .create_from_directory(
            "reload",
            &template_config.host_dir,
            &template_config.dockerfile,
        )
        .await?;
    let template_files = dabgent_agent::sandbox_seed::collect_template_files(
        std::path::Path::new(template_config.template_path.as_ref().unwrap()),
        &template_config.template_base_path,
    )?;
    for (path, content) in template_files.files.iter() {
        sandbox.write_file(path, content).await?;
    }

    let files = sandbox.list_directory(".").await?;
    tracing::info!("Files in directory: {:?}", files);

    tokio::select! {
        _ = signal::ctrl_c() => {},
        _ = run_preview(&sandbox) => {},
    }
    Ok(())
}

async fn run_preview(sandbox: &DaggerSandbox) -> eyre::Result<()> {
    use dagger_sdk::{ContainerUpOptsBuilder, NetworkProtocol, PortForward};
    let ports = vec![
        PortForward {
            backend: 8000,
            frontend: 8000,
            protocol: NetworkProtocol::Tcp,
        },
        PortForward {
            backend: 3000,
            frontend: 3000,
            protocol: NetworkProtocol::Tcp,
        },
    ];
    let opts = ContainerUpOptsBuilder::default()
        .args(vec!["npm", "run", "dev"])
        .ports(ports)
        .build()?;
    let ctr = sandbox
        .container()
        .with_exposed_port(8000)
        .with_exposed_port(3000)
        .with_exec(vec!["npm", "install", "-g", "concurrently"])
        .with_exec(vec!["npm", "install", "--prefix", "frontend"])
        .with_workdir("/app/backend")
        .with_exec(vec!["uv", "sync", "--no-install-project"])
        .with_workdir("/app");
    let _ = ctr.up_opts(opts).await?;
    Ok(())
}
