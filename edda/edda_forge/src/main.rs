mod config;
mod container;
mod runner;
mod state;

use clap::Parser;
use config::{ForgeConfig, RetryTarget};
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

    /// path to forge.toml config file (looked up in source dir if not provided)
    #[arg(long)]
    config: Option<PathBuf>,

    /// path to source directory (used when no config file is found)
    #[arg(long)]
    source: Option<PathBuf>,

    /// output path (default: patch file; with --export-dir: directory)
    #[arg(long, default_value = "./forge-output")]
    output: PathBuf,

    /// max retries per backtrack edge
    #[arg(long, default_value_t = 3)]
    max_retries: usize,

    /// export full directory instead of generating a .patch file
    #[arg(long)]
    export_dir: bool,
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

    // resolve config: explicit --config > forge.toml in --source dir > forge.toml in cwd > default
    let config_path = match &cli.config {
        Some(p) => {
            if !p.exists() {
                bail!("config file not found: {}", p.display());
            }
            Some(p.clone())
        }
        None => {
            // look in --source dir first, then cwd
            let candidates = cli
                .source
                .iter()
                .map(|s| s.join("forge.toml"))
                .chain(std::iter::once(PathBuf::from("forge.toml")));
            candidates.into_iter().find(|p| p.exists())
        }
    };

    let (forge_config, config_dir) = match &config_path {
        Some(p) => {
            info!(config = %p.display(), "loading config");
            let cfg = ForgeConfig::load(p)?;
            let dir = p.parent().unwrap_or(std::path::Path::new(".")).to_path_buf();
            (cfg, dir)
        }
        None => {
            info!("no config file found, using default Rust config");
            (ForgeConfig::default_rust(), PathBuf::from("."))
        }
    };

    let source_path = match &cli.source {
        Some(p) => {
            if !p.exists() {
                bail!("source path does not exist: {}", p.display());
            }
            p.clone()
        }
        None if config_path.is_none() => {
            // no config, no source: use embedded template
            let manifest_dir = env!("CARGO_MANIFEST_DIR");
            let template = std::path::Path::new(manifest_dir).join("template");
            if !template.exists() {
                bail!("embedded template not found at {}", template.display());
            }
            template
        }
        None => config::resolve_source_path(&forge_config, &config_dir)?,
    };

    info!(source = %source_path.display(), "resolved source path");

    let output = cli.output.clone();
    let prompt = cli.prompt.clone();
    let max_retries = cli.max_retries;
    let export_dir = cli.export_dir;

    let opts = ConnectOpts::new(Logger::Tracing, Some(600));
    opts.connect(move |client| async move {
        let mut sandbox =
            container::setup_container(client, &api_key, &forge_config, &source_path).await?;

        // create git baseline for diff output
        info!("creating git baseline commit");
        let workdir = &forge_config.project.workdir;
        let git_init = sandbox
            .exec(&format!(
                "git config --global --add safe.directory {workdir} && \
                 git config --global init.defaultBranch main && \
                 git config --global user.email forge@local && \
                 git config --global user.name forge && \
                 git init && git add -A && git commit -m baseline --allow-empty"
            ))
            .await?;
        if git_init.exit_code != 0 {
            warn!(
                stderr = %git_init.stderr,
                "git baseline setup failed (non-fatal)"
            );
        }

        // clean up stale tasks.md from previous forge runs
        let _ = sandbox.exec("rm -f tasks.md").await;

        let mut state = State::Init { prompt };
        let mut retries = RetryTracker::new(max_retries);

        while !state.is_terminal() {
            let old = format!("{state}");
            state = step(state, &mut sandbox, &mut retries, &forge_config).await;
            info!(from = %old, to = %state, "state transition");
        }

        match &state {
            State::Done => {
                if export_dir {
                    info!(output = %output.display(), "exporting project directory");
                    sandbox
                        .export_directory("/app", &output.to_string_lossy())
                        .await?;
                    info!("directory export complete");
                } else {
                    let patch_path = if output.extension().is_some() {
                        output.clone()
                    } else {
                        output.with_extension("patch")
                    };
                    info!(patch = %patch_path.display(), "generating patch");
                    let diff_result = sandbox
                        .exec("git add -A && git diff --cached")
                        .await?;
                    if diff_result.exit_code != 0 {
                        bail!("git diff failed: {}", diff_result.stderr);
                    }
                    std::fs::write(&patch_path, &diff_result.stdout)?;
                    info!(patch = %patch_path.display(), "patch written");
                }
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
    config: &ForgeConfig,
) -> State {
    let language = &config.project.language;

    match state {
        State::Init { prompt } => State::RewriteTask { prompt },

        State::RewriteTask { prompt } => {
            match runner::rewrite_task(sandbox, &prompt, language).await {
                Ok(task_list) => State::LoadTaskList { task_list },
                Err(e) => State::Failed {
                    reason: format!("RewriteTask: {e}"),
                },
            }
        }

        State::LoadTaskList { task_list } => {
            if config.steps.write_tests {
                State::WriteTests { task_list }
            } else {
                State::WriteCode {
                    task_list,
                    context: None,
                }
            }
        }

        State::WriteTests { task_list } => {
            match runner::write_tests(sandbox, &task_list, language, None).await {
                Ok(()) => State::Validate {
                    phase: Phase::Tests,
                    step_idx: 0,
                },
                Err(e) => State::Failed {
                    reason: format!("WriteTests: {e}"),
                },
            }
        }

        State::WriteCode { task_list, context } => {
            match runner::write_code(sandbox, &task_list, language, context.as_deref()).await {
                Ok(()) => State::Validate {
                    phase: Phase::Code,
                    step_idx: 0,
                },
                Err(e) => State::Failed {
                    reason: format!("WriteCode: {e}"),
                },
            }
        }

        State::Validate { phase, step_idx } => {
            // find the next applicable step
            let steps = &config.steps.validate;

            // in Tests phase, skip steps with retry_on_fail = WriteCode (code doesn't exist yet)
            let applicable_idx = (step_idx..steps.len()).find(|&i| match phase {
                Phase::Tests => steps[i].retry_on_fail != RetryTarget::WriteCode,
                Phase::Code => true,
            });

            let Some(idx) = applicable_idx else {
                // no more steps — advance to next major state
                return match phase {
                    Phase::Tests => State::WriteCode {
                        task_list: read_task_list(sandbox).await,
                        context: None,
                    },
                    Phase::Code => State::Review,
                };
            };

            let step = &steps[idx];

            match runner::run_validate_step(sandbox, step).await {
                Ok(result) if result.exit_code == 0 => {
                    info!(step = %step.name, "validation step passed");
                    // advance to next step
                    State::Validate {
                        phase,
                        step_idx: idx + 1,
                    }
                }
                Ok(result) => {
                    let error_output = format!("{}\n{}", result.stdout, result.stderr);
                    let retry_edge = format!("validate_{}_{}", step.name, phase);
                    // leak to get &'static str for retry tracker
                    let retry_edge: &'static str = Box::leak(retry_edge.into_boxed_str());

                    if retries.try_retry(retry_edge) {
                        warn!(
                            step = %step.name,
                            attempt = retries.count(retry_edge),
                            "validation failed, retrying"
                        );

                        let task_list = read_task_list(sandbox).await;

                        match step.retry_on_fail {
                            RetryTarget::WriteTests => {
                                match runner::write_tests(
                                    sandbox,
                                    &task_list,
                                    language,
                                    Some(&error_output),
                                )
                                .await
                                {
                                    Ok(()) => State::Validate {
                                        phase,
                                        step_idx: 0,
                                    },
                                    Err(e) => State::Failed {
                                        reason: format!("WriteTests retry: {e}"),
                                    },
                                }
                            }
                            RetryTarget::WriteCode => {
                                match runner::write_code(
                                    sandbox,
                                    &task_list,
                                    language,
                                    Some(&error_output),
                                )
                                .await
                                {
                                    Ok(()) => State::Validate {
                                        phase,
                                        step_idx: 0,
                                    },
                                    Err(e) => State::Failed {
                                        reason: format!("WriteCode retry: {e}"),
                                    },
                                }
                            }
                        }
                    } else {
                        State::Failed {
                            reason: format!(
                                "validation step '{}' failed after max retries: {}",
                                step.name,
                                truncate_string(&error_output, 500)
                            ),
                        }
                    }
                }
                Err(e) => State::Failed {
                    reason: format!("validation step '{}' exec error: {e}", step.name),
                },
            }
        }

        State::Review => {
            let task_list = read_task_list(sandbox).await;
            match runner::review(sandbox, &task_list, language).await {
                Ok(runner::ReviewVerdict::Approved) => {
                    info!("review approved");
                    State::Export
                }
                Ok(runner::ReviewVerdict::Rejected { feedback }) => {
                    if retries.try_retry("review") {
                        warn!(
                            attempt = retries.count("review"),
                            feedback = %feedback,
                            "review rejected, retrying WriteCode"
                        );
                        let task_list = read_task_list(sandbox).await;
                        match runner::write_code(sandbox, &task_list, language, Some(&feedback))
                            .await
                        {
                            Ok(()) => State::Validate {
                                phase: Phase::Code,
                                step_idx: 0,
                            },
                            Err(e) => State::Failed {
                                reason: format!("WriteCode retry after review rejection: {e}"),
                            },
                        }
                    } else {
                        State::Failed {
                            reason: format!(
                                "review rejected after max retries: {}",
                                truncate_string(&feedback, 500)
                            ),
                        }
                    }
                }
                Ok(runner::ReviewVerdict::InvalidFormat) => {
                    if retries.try_retry("review_format") {
                        warn!(
                            attempt = retries.count("review_format"),
                            "review returned invalid format, retrying review"
                        );
                        State::Review
                    } else {
                        State::Failed {
                            reason: "review returned invalid format after max retries".into(),
                        }
                    }
                }
                Err(e) => State::Failed {
                    reason: format!("review exec error: {e}"),
                },
            }
        }

        State::Export => State::Done,

        State::Done | State::Failed { .. } => state,
    }
}

async fn read_task_list(sandbox: &mut impl Sandbox) -> String {
    sandbox
        .read_file("/app/tasks.md")
        .await
        .unwrap_or_else(|e| {
            warn!(error = %e, "failed to read tasks.md");
            "no task list available".to_string()
        })
}

fn truncate_string(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}...", &s[..max])
    }
}
