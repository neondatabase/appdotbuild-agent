use dabgent_agent::processor::finish::ArtifactPreparer;
use dabgent_sandbox::SandboxDyn;
use eyre::Result;

pub struct DataAppsArtifactPreparer;

impl ArtifactPreparer for DataAppsArtifactPreparer {
    fn prepare(&self, sandbox: &mut Box<dyn SandboxDyn>) -> impl std::future::Future<Output = Result<()>> + Send {
        async move {
        tracing::info!("Starting requirements export...");

        let result = sandbox.exec("cd /app/backend && uv export --no-hashes --format requirements-txt --output-file requirements.txt --no-dev")
            .await.map_err(|e| {
                let error = format!("Failed to run uv export: {}", e);
                tracing::error!("{}", error);
                eyre::eyre!(error)
            })?;

        if result.exit_code != 0 {
            let error_msg = format!(
                "uv export command failed (exit code {}): stderr: {} stdout: {}",
                result.exit_code,
                result.stderr,
                result.stdout
            );
            tracing::error!("Requirements export failed: {}", error_msg);
            return Err(eyre::eyre!(error_msg));
        }

        tracing::info!("Requirements export completed successfully");
        Ok(())
        }
    }
}