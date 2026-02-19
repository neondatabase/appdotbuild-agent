mod config;
mod container;
mod local;
mod runner;
mod state;

use clap::{Parser, ValueEnum};
use config::ForgeConfig;
use edda_sandbox::Sandbox;
use edda_sandbox::dagger::{ConnectOpts, Logger};
use eyre::{Result, bail};
use state::State;
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Instant;
use tracing::{error, info, warn};

#[derive(Copy, Clone, Debug, Eq, PartialEq, ValueEnum)]
enum RuntimeBackend {
    Dagger,
    Local,
}

#[derive(Parser)]
#[command(
    name = "edda-forge",
    about = "Generates validated git patches from natural language prompts",
    long_about = "\
Generates validated git patches from natural language prompts.

Runs Claude Code or OpenCode through a deterministic state machine:
  Init → Plan → Work (loop) → Validate → Review → Export

The Plan stage creates a checkbox task list (tasks.md). Each Work iteration calls
the agent to work on unchecked items and mark them done. Once all tasks are checked off,
validation runs. Failures append fix tasks to the list and loop back to Work.

Output is a unified diff that has passed all configured validation steps (build, test, etc.)
and a self-review. Apply with `git apply`.",
    after_long_help = "\
CONFIGURATION:
  Behavior is driven by a forge.toml config file. Resolution order:
    1. Explicit --config path (must exist)
    2. forge.toml in --source directory
    3. forge.toml in current working directory
    4. Built-in default (Rust project with cargo check/test/bench)

  See the forge.toml reference for container, project, and validation step settings.

ENVIRONMENT:
  ANTHROPIC_API_KEY    Required for dagger+claude. Optional in local runtime.
  RUST_LOG             Optional. Controls log verbosity (default: edda_forge=info).

RUNTIME NOTES:
  --runtime local:
    - ignores [container].setup/user/user_setup and [container.env]
    - mounts must be under project.workdir or define mounts.local_target
    - OpenCode auth/config uses host state directly (no auth mount required)

EXAMPLES:
  # generate a patch from a prompt (uses dagger runtime by default)
  edda-forge --prompt 'add a CLI that parses --name and prints a greeting'

  # run without dagger (host-local execution)
  edda-forge --runtime local --prompt 'add input validation'

  # use a custom config and source directory
  edda-forge --prompt 'add input validation' --config ./forge.toml --source ./my-project

  # export the full project directory instead of a patch
  edda-forge --prompt 'implement a REST API' --export-dir --output ./generated-app

  # allow more retries for flaky validation steps
  edda-forge --prompt 'add benchmarks' --max-retries 5"
)]
struct Cli {
    /// Natural language task description for code generation
    #[arg(long, required_unless_present = "install_claude")]
    prompt: Option<String>,

    /// Install the /forge slash command for Claude Code (~/.claude/commands/forge.md)
    #[arg(long)]
    install_claude: bool,

    /// Path to forge.toml config file
    ///
    /// If not provided, looks for forge.toml in --source dir, then cwd.
    /// Falls back to the built-in default Rust config if nothing is found.
    #[arg(long, value_name = "PATH")]
    config: Option<PathBuf>,

    /// Path to source directory to copy into the runtime workspace
    ///
    /// If omitted and a config is found, resolves from config's project.source field.
    /// If omitted and no config is found, uses the embedded Rust template.
    #[arg(long, value_name = "DIR")]
    source: Option<PathBuf>,

    /// Output path for the result
    ///
    /// Without --export-dir: writes a .patch file (extension added automatically).
    /// With --export-dir: exports the full project directory to this path.
    #[arg(long, default_value = "./forge-output", value_name = "PATH")]
    output: PathBuf,

    /// Max retries for validation and review failures
    #[arg(long, default_value_t = 3, value_name = "N")]
    max_retries: usize,

    /// Runtime backend (`dagger` for containerized runs, `local` for host execution)
    #[arg(long, value_enum, default_value_t = RuntimeBackend::Local)]
    runtime: RuntimeBackend,

    /// Export the full project directory instead of generating a .patch file
    #[arg(long)]
    export_dir: bool,
}

#[tokio::main]
async fn main() -> ExitCode {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("edda_forge=info")),
        )
        .init();

    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) if is_interrupt(&e) => {
            info!("interrupted");
            ExitCode::from(130)
        }
        Err(e) => {
            error!("{e:?}");
            ExitCode::FAILURE
        }
    }
}

fn is_interrupt(err: &eyre::Report) -> bool {
    // tokio::signal race returns this; also check nested io errors
    if let Some(io) = err.downcast_ref::<std::io::Error>() {
        return io.kind() == std::io::ErrorKind::Interrupted;
    }
    format!("{err:?}").contains("interrupted")
}

async fn run() -> Result<()> {
    let cli = Cli::parse();

    if cli.install_claude {
        return install_claude_command();
    }

    let prompt = cli.prompt.expect("--prompt is required");

    if let Ok(home) = std::env::var("HOME") {
        let cmd_path = PathBuf::from(home).join(".claude/commands/forge.md");
        if !cmd_path.exists() {
            eprintln!(
                "hint: run `edda-forge --install-claude` to install the /forge slash command for Claude Code"
            );
        }
    }

    // resolve config: explicit --config > forge.toml in --source dir > forge.toml in cwd > default
    let config_path = match &cli.config {
        Some(p) => {
            if !p.exists() {
                bail!("config file not found: {}", p.display());
            }
            Some(p.clone())
        }
        None => {
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
            let dir = p
                .parent()
                .unwrap_or(std::path::Path::new("."))
                .to_path_buf();
            (cfg, dir)
        }
        None => {
            info!("no config file found, using default Rust config");
            (ForgeConfig::default_rust(), PathBuf::from("."))
        }
    };

    let agent_auth = match &forge_config.agent.backend {
        config::AgentBackend::Claude => {
            let api_key = std::env::var("ANTHROPIC_API_KEY").ok();
            if matches!(cli.runtime, RuntimeBackend::Dagger) && api_key.is_none() {
                bail!("ANTHROPIC_API_KEY not set (required for dagger runtime)");
            }
            container::AgentAuth {
                api_key,
                opencode_auth_file: None,
                opencode_config_dir: None,
            }
        }
        config::AgentBackend::OpenCode => {
            let home = std::env::var("HOME").map_err(|_| eyre::eyre!("HOME not set"))?;
            let auth_file = PathBuf::from(&home).join(".local/share/opencode/auth.json");
            let config_dir = PathBuf::from(&home).join(".config/opencode");
            if !auth_file.exists() && !config_dir.exists() {
                warn!("no opencode auth/config found — run `opencode` and `/connect` first");
            }
            container::AgentAuth {
                api_key: std::env::var("ANTHROPIC_API_KEY").ok(),
                opencode_auth_file: auth_file
                    .exists()
                    .then(|| auth_file.to_string_lossy().into()),
                opencode_config_dir: config_dir
                    .exists()
                    .then(|| config_dir.to_string_lossy().into()),
            }
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
    let max_retries = cli.max_retries;
    let export_dir = cli.export_dir;
    let runtime = cli.runtime;

    match runtime {
        RuntimeBackend::Dagger => {
            // Claude installer + first cold container materialization can exceed the
            // default timeout, especially when multiple forge runs execute in parallel.
            let opts = ConnectOpts::new(Logger::Tracing, Some(3600));
            opts.connect(move |client| async move {
                let mut sandbox = container::setup_container(
                    client,
                    &agent_auth,
                    &forge_config,
                    &source_path,
                    &config_dir,
                )
                .await?;
                run_pipeline(
                    &mut sandbox,
                    prompt,
                    output,
                    max_retries,
                    export_dir,
                    &forge_config,
                )
                .await?;

                // flatten chained Dagger queries before finalization
                sandbox.sync().await?;
                Ok(())
            })
            .await
            .map_err(|e| {
                let mut msg = format!("dagger error: {e}");
                let mut source: &dyn std::error::Error = &e;
                while let Some(cause) = source.source() {
                    msg.push_str(&format!("\n  caused by: {cause}"));
                    source = cause;
                }
                eyre::eyre!(msg)
            })?;
        }
        RuntimeBackend::Local => {
            info!("using local runtime backend (no dagger)");
            let mut run =
                local::setup_local_sandbox(&agent_auth, &forge_config, &source_path, &config_dir)?;
            run_pipeline(
                &mut run.sandbox,
                prompt,
                output,
                max_retries,
                export_dir,
                &forge_config,
            )
            .await?;
        }
    }

    Ok(())
}

async fn run_pipeline(
    sandbox: &mut impl Sandbox,
    prompt: String,
    output: PathBuf,
    max_retries: usize,
    export_dir: bool,
    forge_config: &ForgeConfig,
) -> Result<()> {
    // create git baseline for diff output
    info!("creating git baseline commit");
    let workdir = &forge_config.project.workdir;
    let git_init = sandbox
        .exec(
            "git init && \
             (git symbolic-ref HEAD refs/heads/main >/dev/null 2>&1 || true) && \
             git config user.email forge@local && \
             git config user.name forge && \
             git add -A && git commit -m baseline --allow-empty",
        )
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
    let mut validate_retries = 0usize;
    let mut review_retries = 0usize;
    let run_start = Instant::now();

    while !state.is_terminal() {
        let old = format!("{state}");
        let step_start = Instant::now();

        // race each step against Ctrl+C so we exit promptly on interrupt
        let next = tokio::select! {
            s = step(
                state,
                sandbox,
                &mut validate_retries,
                &mut review_retries,
                max_retries,
                forge_config,
            ) => s,
            _ = tokio::signal::ctrl_c() => {
                bail!("interrupted");
            }
        };
        state = next;

        info!(
            from = %old,
            to = %state,
            elapsed_secs = step_start.elapsed().as_secs(),
            "state transition"
        );
    }
    info!(total_secs = run_start.elapsed().as_secs(), "forge finished");

    match &state {
        State::Done => {
            if export_dir {
                info!(output = %output.display(), "exporting project directory");
                sandbox
                    .export_directory(workdir, &output.to_string_lossy())
                    .await?;
                info!("directory export complete");
            } else {
                let patch_path = if output.extension().is_some() {
                    output.clone()
                } else {
                    output.with_extension("patch")
                };
                info!(patch = %patch_path.display(), "generating patch");
                // stage everything and discover binary files
                let numstat = sandbox
                    .exec("git add -A && git diff --cached --numstat")
                    .await?;
                let mut pathspec = forge_config.patch.git_diff_pathspec();
                for line in numstat.stdout.lines() {
                    // binary files show as "-\t-\tpath"
                    let parts: Vec<&str> = line.splitn(3, '\t').collect();
                    if parts.len() == 3 && parts[0] == "-" && parts[1] == "-" {
                        pathspec.push_str(&format!(" ':(exclude){}'", parts[2]));
                    }
                }
                let diff_result = sandbox
                    .exec(&format!("git diff --cached {pathspec}"))
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
}

async fn step(
    state: State,
    sandbox: &mut impl Sandbox,
    validate_retries: &mut usize,
    review_retries: &mut usize,
    max_retries: usize,
    config: &ForgeConfig,
) -> State {
    let language = &config.project.language;
    let agent = &config.agent;
    let workdir = &config.project.workdir;

    match state {
        State::Init { prompt } => State::Plan { prompt },

        State::Plan { prompt } => match runner::plan(sandbox, agent, &prompt, language, workdir)
            .await
        {
            Ok(()) => match runner::read_tasks(sandbox, workdir).await {
                Ok(tasks) => {
                    let stats = runner::parse_task_stats(&tasks);
                    if stats.pending == 0 {
                        return State::Failed {
                            reason: "Plan produced no tasks (no `- [ ]` items in tasks.md)".into(),
                        };
                    }
                    info!(tasks = stats.pending, "plan created");
                    for task in &stats.pending_tasks {
                        info!(task = %task, "planned");
                    }
                    State::Work
                }
                Err(e) => State::Failed {
                    reason: format!("reading tasks.md after plan: {e}"),
                },
            },
            Err(e) => State::Failed {
                reason: format!("Plan: {e}"),
            },
        },

        State::Work => {
            let before = match runner::read_tasks(sandbox, workdir).await {
                Ok(tasks) => {
                    let stats = runner::parse_task_stats(&tasks);
                    if stats.pending == 0 {
                        info!(done = stats.done, "all tasks done, moving to validation");
                        return State::Validate { step_idx: 0 };
                    }
                    info!(
                        pending = stats.pending,
                        done = stats.done,
                        "working on remaining tasks"
                    );
                    stats
                }
                Err(e) => {
                    return State::Failed {
                        reason: format!("reading tasks.md: {e}"),
                    };
                }
            };

            if let Err(e) = runner::work(sandbox, agent, language, workdir).await {
                return State::Failed {
                    reason: format!("Work: {e}"),
                };
            }

            match runner::read_tasks(sandbox, workdir).await {
                Ok(tasks) => {
                    let after = runner::parse_task_stats(&tasks);
                    if after.done <= before.done {
                        State::Failed {
                            reason: format!(
                                "Work made no progress ({} tasks still pending)",
                                after.pending
                            ),
                        }
                    } else {
                        let newly_done = after.done - before.done;
                        // log each newly completed task
                        for task in after.done_tasks.iter().skip(before.done) {
                            info!(task = %task, "completed");
                        }
                        info!(
                            completed = newly_done,
                            done = after.done,
                            pending = after.pending,
                            "work iteration finished"
                        );
                        State::Work
                    }
                }
                Err(e) => State::Failed {
                    reason: format!("reading tasks.md after work: {e}"),
                },
            }
        }

        State::Validate { step_idx } => {
            let steps = &config.steps.validate;

            if step_idx >= steps.len() {
                return State::Review;
            }

            let step = &steps[step_idx];

            match runner::run_validate_step(sandbox, step).await {
                Ok(result) if result.exit_code == 0 => {
                    info!(step = %step.name, "validation step passed");
                    State::Validate {
                        step_idx: step_idx + 1,
                    }
                }
                Ok(result) => {
                    let error_output = format!("{}\n{}", result.stdout, result.stderr);
                    *validate_retries += 1;
                    if *validate_retries > max_retries {
                        return State::Failed {
                            reason: format!(
                                "validation step '{}' failed after {} retries: {}",
                                step.name,
                                max_retries,
                                truncate_string(&error_output, 500)
                            ),
                        };
                    }

                    warn!(
                        step = %step.name,
                        attempt = *validate_retries,
                        "validation failed, appending fix task"
                    );

                    let description = format!(
                        "Fix: `{}` failed (attempt {}) — {}",
                        step.name,
                        *validate_retries,
                        truncate_string(&error_output, 300)
                    );
                    match runner::append_task(sandbox, &description, workdir).await {
                        Ok(()) => State::Work,
                        Err(e) => State::Failed {
                            reason: format!("failed to append fix task: {e}"),
                        },
                    }
                }
                Err(e) => State::Failed {
                    reason: format!("validation step '{}' exec error: {e}", step.name),
                },
            }
        }

        State::Review => {
            match runner::review(
                sandbox,
                agent,
                language,
                workdir,
                &config.patch.git_diff_pathspec(),
            )
            .await
            {
                Ok(runner::ReviewVerdict::Approved) => {
                    info!("review approved");
                    State::Export
                }
                Ok(runner::ReviewVerdict::Rejected { feedback }) => {
                    *review_retries += 1;
                    if *review_retries > max_retries {
                        return State::Failed {
                            reason: format!(
                                "review rejected after {} retries: {}",
                                max_retries,
                                truncate_string(&feedback, 500)
                            ),
                        };
                    }

                    warn!(
                        attempt = *review_retries,
                        feedback = %feedback,
                        "review rejected, appending fix task"
                    );

                    let description = format!(
                        "Fix: review rejected (attempt {}) — {}",
                        *review_retries, feedback
                    );
                    match runner::append_task(sandbox, &description, workdir).await {
                        Ok(()) => State::Work,
                        Err(e) => State::Failed {
                            reason: format!("failed to append fix task: {e}"),
                        },
                    }
                }
                Ok(runner::ReviewVerdict::InvalidFormat) => {
                    *review_retries += 1;
                    if *review_retries > max_retries {
                        return State::Failed {
                            reason: "review returned invalid format after max retries".into(),
                        };
                    }
                    warn!(
                        attempt = *review_retries,
                        "review returned invalid format, retrying"
                    );
                    State::Review
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

fn install_claude_command() -> Result<()> {
    const COMMAND: &str = include_str!("../forge-command.md");
    let home = std::env::var("HOME").map_err(|_| eyre::eyre!("HOME not set"))?;
    let dir = PathBuf::from(home).join(".claude/commands");
    std::fs::create_dir_all(&dir)?;
    let path = dir.join("forge.md");
    std::fs::write(&path, COMMAND)?;
    println!("installed /forge command → {}", path.display());
    Ok(())
}

fn truncate_string(s: &str, max: usize) -> String {
    match s.get(..max) {
        Some(prefix) => format!("{prefix}..."),
        None => s.to_string(),
    }
}
