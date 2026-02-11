mod container;
mod runner;
mod state;

use clap::Parser;
use edda_sandbox::Sandbox;
use edda_sandbox::dagger::{ConnectOpts, Logger};
use eyre::{Result, bail};
use state::{Phase, RetryTracker, State};
use std::path::PathBuf;
use tracing::{error, info, warn};

#[derive(Parser)]
#[command(name = "edda-forge", about = "Deterministic coding agent")]
struct Cli {
    /// task description for code generation
    #[arg(long)]
    prompt: String,

    /// path to custom Rust project template
    #[arg(long)]
    template: Option<PathBuf>,

    /// host directory for exported project
    #[arg(long, default_value = "./forge-output")]
    output: PathBuf,

    /// max retries per backtrack edge
    #[arg(long, default_value_t = 3)]
    max_retries: usize,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("edda_forge=info")),
        )
        .init();

    let cli = Cli::parse();

    let api_key = std::env::var("ANTHROPIC_API_KEY")
        .map_err(|_| eyre::eyre!("ANTHROPIC_API_KEY not set"))?;

    let template_path = container::resolve_template_path(cli.template.as_deref())?;
    info!(template = %template_path.display(), "resolved template");

    let output = cli.output.clone();
    let prompt = cli.prompt.clone();
    let max_retries = cli.max_retries;

    let opts = ConnectOpts::new(Logger::Tracing, Some(600));
    opts.connect(move |client| async move {
        let mut sandbox =
            container::setup_container(client, &api_key, &template_path).await?;

        let mut state = State::Init { prompt };
        let mut retries = RetryTracker::new(max_retries);

        while !state.is_terminal() {
            let old = format!("{state}");
            state = step(state, &mut sandbox, &mut retries).await;
            info!(from = %old, to = %state, "state transition");
        }

        match &state {
            State::Done => {
                info!(output = %output.display(), "exporting project");
                sandbox.export_directory("/app", &output.to_string_lossy()).await?;
                info!("export complete");
            }
            State::Failed { reason } => {
                error!(%reason, "forge failed");
                bail!("forge failed: {reason}");
            }
            _ => unreachable!(),
        }

        Ok(())
    })
    .await
    .map_err(|e| eyre::eyre!("dagger error: {e}"))?;

    Ok(())
}

async fn step(
    state: State,
    sandbox: &mut impl Sandbox,
    retries: &mut RetryTracker,
) -> State {
    match state {
        State::Init { prompt } => State::RewriteTask { prompt },

        State::RewriteTask { prompt } => match runner::rewrite_task(sandbox, &prompt).await {
            Ok(_task_list) => State::CloneTemplate,
            Err(e) => State::Failed {
                reason: format!("RewriteTask: {e}"),
            },
        },

        State::CloneTemplate => {
            // template is already mounted at /app during container setup
            State::WriteTests {
                task_list: read_task_list(sandbox).await,
            }
        }

        State::WriteTests { task_list } => {
            match runner::write_tests(sandbox, &task_list, None).await {
                Ok(()) => State::CargoCheck {
                    phase: Phase::Tests,
                },
                Err(e) => State::Failed {
                    reason: format!("WriteTests: {e}"),
                },
            }
        }

        State::CargoCheck { phase } => {
            match runner::cargo_check(sandbox).await {
                Ok(result) if result.exit_code == 0 => match phase {
                    Phase::Tests => State::WriteCode {
                        task_list: read_task_list(sandbox).await,
                        context: None,
                    },
                    Phase::Code => State::RunTests,
                },
                Ok(result) => {
                    let error_output = format!("{}\n{}", result.stdout, result.stderr);
                    match phase {
                        Phase::Tests => {
                            if retries.try_retry("cargo_check_tests") {
                                warn!(
                                    attempt = retries.count("cargo_check_tests"),
                                    "cargo check failed after WriteTests, retrying"
                                );
                                let task_list = read_task_list(sandbox).await;
                                // retry WriteTests with error context, then re-check
                                match runner::write_tests(sandbox, &task_list, Some(&error_output))
                                    .await
                                {
                                    Ok(()) => State::CargoCheck {
                                        phase: Phase::Tests,
                                    },
                                    Err(e) => State::Failed {
                                        reason: format!("WriteTests retry: {e}"),
                                    },
                                }
                            } else {
                                State::Failed {
                                    reason: format!(
                                        "cargo check (tests) failed after max retries: {}",
                                        truncate_string(&error_output, 500)
                                    ),
                                }
                            }
                        }
                        Phase::Code => {
                            if retries.try_retry("cargo_check_code") {
                                warn!(
                                    attempt = retries.count("cargo_check_code"),
                                    "cargo check failed after WriteCode, retrying"
                                );
                                let task_list = read_task_list(sandbox).await;
                                match runner::write_code(
                                    sandbox,
                                    &task_list,
                                    Some(&error_output),
                                )
                                .await
                                {
                                    Ok(()) => State::CargoCheck {
                                        phase: Phase::Code,
                                    },
                                    Err(e) => State::Failed {
                                        reason: format!("WriteCode retry: {e}"),
                                    },
                                }
                            } else {
                                State::Failed {
                                    reason: format!(
                                        "cargo check (code) failed after max retries: {}",
                                        truncate_string(&error_output, 500)
                                    ),
                                }
                            }
                        }
                    }
                }
                Err(e) => State::Failed {
                    reason: format!("cargo check exec error: {e}"),
                },
            }
        }

        State::WriteCode { task_list, context } => {
            match runner::write_code(sandbox, &task_list, context.as_deref()).await {
                Ok(()) => State::CargoCheck {
                    phase: Phase::Code,
                },
                Err(e) => State::Failed {
                    reason: format!("WriteCode: {e}"),
                },
            }
        }

        State::RunTests => match runner::run_tests(sandbox).await {
            Ok(result) if result.exit_code == 0 => {
                info!("all tests passed");
                State::RunBenchmark
            }
            Ok(result) => {
                let error_output = format!("{}\n{}", result.stdout, result.stderr);
                if retries.try_retry("run_tests") {
                    warn!(
                        attempt = retries.count("run_tests"),
                        "tests failed, retrying WriteCode"
                    );
                    let task_list = read_task_list(sandbox).await;
                    match runner::write_code(sandbox, &task_list, Some(&error_output)).await {
                        Ok(()) => State::CargoCheck {
                            phase: Phase::Code,
                        },
                        Err(e) => State::Failed {
                            reason: format!("WriteCode retry after test failure: {e}"),
                        },
                    }
                } else {
                    State::Failed {
                        reason: format!(
                            "tests failed after max retries: {}",
                            truncate_string(&error_output, 500)
                        ),
                    }
                }
            }
            Err(e) => State::Failed {
                reason: format!("cargo test exec error: {e}"),
            },
        },

        State::RunBenchmark => {
            match runner::run_benchmark(sandbox).await {
                Ok(result) => {
                    if result.exit_code != 0 {
                        warn!("benchmarks failed (non-fatal): {}", result.stderr);
                    } else {
                        info!("benchmarks completed");
                    }
                }
                Err(e) => {
                    warn!("benchmark exec error (non-fatal): {e}");
                }
            }
            State::Export
        }

        State::Export => State::Done,

        State::Done | State::Failed { .. } => state,
    }
}

async fn read_task_list(sandbox: &mut impl Sandbox) -> String {
    sandbox
        .read_file("/app/tasks.md")
        .await
        .unwrap_or_else(|_| "no task list available".to_string())
}

fn truncate_string(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}...", &s[..max])
    }
}
