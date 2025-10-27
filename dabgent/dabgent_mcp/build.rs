use dabgent_sandbox::dagger::{ConnectOpts, Logger};
use dabgent_sandbox::{DaggerSandbox, Sandbox};
use dabgent_templates::TemplateTRPC;

fn main() {
    // skip Dagger warmup in CI - it's only useful for local dev
    if std::env::var("CI").is_ok() {
        println!("cargo:info=Skipping Dagger warmup in CI");
        return;
    }

    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(async {
            let opts = ConnectOpts::default()
                .with_logger(Logger::Silent)
                .with_execute_timeout(Some(600));
            opts.connect(|client| async move {
                let container = client
                    .container()
                    .from("node:20-alpine3.22")
                    .with_exec(vec!["mkdir", "-p", "/app"]);
                let mut sandbox = DaggerSandbox::from_container(container, client.clone());
                let mut files = Vec::new();
                for path in TemplateTRPC::iter() {
                    if let Some(file) = TemplateTRPC::get(path.as_ref()) {
                        let content = String::from_utf8_lossy(&file.data).into_owned();
                        let sandbox_path = format!("/app/{}", path.as_ref());
                        files.push((sandbox_path, content));
                    }
                }
                let files_ref = files
                    .iter()
                    .map(|(p, c)| (p.as_str(), c.as_str()))
                    .collect();
                sandbox.write_files(files_ref).await.unwrap();
                let result = sandbox.list_directory("/app").await;
                println!("TemplateTRPC: {result:?}");
                Ok(())
            })
            .await
            .unwrap();
        })
}
