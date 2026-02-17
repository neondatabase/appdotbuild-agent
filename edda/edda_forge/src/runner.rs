use crate::config::{AgentBackend, AgentConfig, ValidateStep};
use edda_sandbox::{ExecResult, Sandbox};
use eyre::{Result, bail};
use serde::Deserialize;
use tracing::{debug, info, warn};

fn agent_cmd(agent: &AgentConfig, prompt: &str, trajectory: bool) -> String {
    let escaped = prompt.replace('\'', "'\\''");
    let model_flag = agent
        .model
        .as_deref()
        .map(|m| format!(" --model {m}"))
        .unwrap_or_default();
    match &agent.backend {
        AgentBackend::Claude => {
            let traj_flags = if trajectory {
                " --output-format stream-json --verbose"
            } else {
                ""
            };
            format!("claude -p '{escaped}'{model_flag} --dangerously-skip-permissions{traj_flags}")
        }
        AgentBackend::OpenCode => {
            format!("opencode run{model_flag} '{escaped}'")
        }
    }
}

fn log_exec(result: &ExecResult, step: &str) {
    debug!(
        step,
        exit_code = result.exit_code,
        stdout_len = result.stdout.len(),
        stderr_len = result.stderr.len(),
        stdout_tail = %truncate_tail(&result.stdout, 500),
        stderr_tail = %truncate_tail(&result.stderr, 500),
        "exec output"
    );
}

fn check_exec(result: &ExecResult, step: &str) -> Result<()> {
    if result.exit_code != 0 {
        warn!(
            step,
            exit_code = result.exit_code,
            stdout = %result.stdout,
            stderr = %result.stderr,
            "step failed"
        );
        bail!(
            "{step} failed (exit {}):\nstdout: {}\nstderr: {}",
            result.exit_code,
            result.stdout,
            result.stderr
        );
    }
    log_exec(result, step);
    Ok(())
}

fn truncate_tail(s: &str, max: usize) -> &str {
    let len = s.len();
    if len <= max {
        return s;
    }
    let mut start = len - max;
    while !s.is_char_boundary(start) {
        start += 1;
    }
    &s[start..]
}

// --- stream-json trajectory parsing ---

#[derive(Deserialize)]
struct TrajectoryLine {
    #[serde(rename = "type")]
    msg_type: String,
    #[serde(default)]
    message: Option<AssistantMessage>,
    // result fields
    #[serde(default)]
    num_turns: Option<u32>,
    #[serde(default)]
    total_cost_usd: Option<f64>,
    #[serde(default)]
    is_error: Option<bool>,
    // tool result content
    #[serde(default)]
    content: Option<serde_json::Value>,
}

#[derive(Deserialize)]
struct AssistantMessage {
    #[serde(default)]
    content: Vec<ContentBlock>,
}

#[derive(Deserialize)]
#[serde(tag = "type")]
enum ContentBlock {
    #[serde(rename = "text")]
    Text { text: String },
    #[serde(rename = "tool_use")]
    ToolUse {
        name: String,
        #[serde(default)]
        input: serde_json::Value,
    },
    #[serde(other)]
    Other,
}

/// log each line of a stream-json trajectory
fn log_trajectory(stdout: &str, step: &str) {
    for line in stdout.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let parsed: TrajectoryLine = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(e) => {
                warn!(step, error = %e, line = %truncate_tail(line, 200), "failed to parse trajectory line");
                continue;
            }
        };
        match parsed.msg_type.as_str() {
            "assistant" => {
                if let Some(msg) = &parsed.message {
                    for block in &msg.content {
                        match block {
                            ContentBlock::Text { text } => {
                                info!(step, text = %truncate_tail(text, 200), "agent text");
                            }
                            ContentBlock::ToolUse { name, input } => {
                                let args = serde_json::to_string(input).unwrap_or_default();
                                info!(step, tool = %name, args = %truncate_tail(&args, 200), "agent tool_use");
                            }
                            ContentBlock::Other => {}
                        }
                    }
                }
            }
            "tool" => {
                if let Some(content) = &parsed.content {
                    let s = match content {
                        serde_json::Value::String(s) => s.clone(),
                        other => serde_json::to_string(other).unwrap_or_default(),
                    };
                    debug!(step, result = %truncate_tail(&s, 300), "tool result");
                }
            }
            "result" => {
                info!(
                    step,
                    turns = parsed.num_turns.unwrap_or(0),
                    cost_usd = parsed.total_cost_usd.unwrap_or(0.0),
                    is_error = parsed.is_error.unwrap_or(false),
                    "agent finished"
                );
            }
            _ => {}
        }
    }
}

/// ask the agent to decompose the prompt into a checkbox task list (tasks.md)
pub async fn plan(
    sandbox: &mut impl Sandbox,
    agent: &AgentConfig,
    prompt: &str,
    language: &str,
) -> Result<()> {
    let instruction = format!(
        "You are working in /app, a {language} project. \
         The user wants: {prompt}\n\n\
         Create a file called /app/tasks.md with a markdown checkbox task list \
         that breaks this down into implementation steps. Use this format:\n\
         - [ ] First task\n\
         - [ ] Second task\n\n\
         Include writing tests as part of the plan. \
         Focus on the public API, data structures, and key algorithms. \
         Do NOT write any code yet — only the task list."
    );

    info!("creating task plan");
    let result = sandbox.exec(&agent_cmd(agent, &instruction, true)).await?;
    log_trajectory(&result.stdout, "Plan");
    check_exec(&result, "Plan")?;

    let task_list = sandbox.read_file("/app/tasks.md").await?;
    if task_list.trim().is_empty() {
        bail!("Plan produced empty tasks.md");
    }
    debug!(task_list_len = task_list.len(), "tasks.md created");
    Ok(())
}

pub struct TaskStats {
    pub done: usize,
    pub pending: usize,
    /// descriptions of newly completed tasks (for logging)
    pub done_tasks: Vec<String>,
    /// descriptions of still-pending tasks (for logging)
    pub pending_tasks: Vec<String>,
}

pub fn parse_task_stats(task_list: &str) -> TaskStats {
    let mut done = 0;
    let mut pending = 0;
    let mut done_tasks = Vec::new();
    let mut pending_tasks = Vec::new();
    for line in task_list.lines() {
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix("- [x]").or_else(|| trimmed.strip_prefix("- [X]")) {
            done += 1;
            done_tasks.push(rest.trim().to_string());
        } else if let Some(rest) = trimmed.strip_prefix("- [ ]") {
            pending += 1;
            pending_tasks.push(rest.trim().to_string());
        }
    }
    TaskStats { done, pending, done_tasks, pending_tasks }
}

/// ask the agent to work on unchecked tasks and check them off
pub async fn work(sandbox: &mut impl Sandbox, agent: &AgentConfig, language: &str) -> Result<()> {
    let task_list = read_tasks(sandbox).await?;

    let instruction = format!(
        "You are working in /app, a {language} project. \
         Here is the current task list from /app/tasks.md:\n\n{task_list}\n\n\
         Work on the unchecked tasks (- [ ]). For each task you complete, \
         update /app/tasks.md to mark it as done (- [x]). \
         You may complete multiple tasks in one go. \
         Focus on correctness.\n\n\
         IMPORTANT: Do NOT create summary/report files (SUMMARY.md, REPORT.md, etc.), \
         scratch test scripts at the project root, or virtual environments. \
         Only create files that are part of the project deliverable."
    );

    info!("working on unchecked tasks");
    let result = sandbox.exec(&agent_cmd(agent, &instruction, true)).await?;
    log_trajectory(&result.stdout, "Work");
    check_exec(&result, "Work")?;
    Ok(())
}

/// append a fix task to tasks.md
pub async fn append_task(
    sandbox: &mut impl Sandbox,
    description: &str,
) -> Result<()> {
    let task_list = read_tasks(sandbox).await?;
    let updated = format!("{task_list}\n- [ ] {description}\n");
    sandbox.write_file("/app/tasks.md", &updated).await?;
    info!(task = %description, "appended fix task");
    Ok(())
}

pub async fn read_tasks(sandbox: &mut impl Sandbox) -> Result<String> {
    let content = sandbox.read_file("/app/tasks.md").await?;
    if content.trim().is_empty() {
        bail!("tasks.md is empty");
    }
    Ok(content)
}

pub enum ReviewVerdict {
    Approved,
    Rejected { feedback: String },
    InvalidFormat,
}

/// ask the agent to review the diff
pub async fn review(sandbox: &mut impl Sandbox, agent: &AgentConfig, language: &str, diff_pathspec: &str) -> Result<ReviewVerdict> {
    let task_list = match read_tasks(sandbox).await {
        Ok(tasks) => tasks,
        Err(e) => {
            warn!("could not read tasks.md for review context: {e}");
            String::new()
        }
    };
    // stage all changes so the agent can inspect via `git diff --cached`
    let stage = sandbox.exec("git add -A").await?;
    if stage.exit_code != 0 {
        bail!("git add -A failed: {}", stage.stderr);
    }

    let instruction = format!(
        "You are a {language} code reviewer working in /app. \
         Review the staged changes (run `git diff --cached {diff_pathspec}` to see the diff).\n\n\
         Task list:\n{task_list}\n\n\
         Check for correctness and bugs only. Do NOT write or modify any files.\n\n\
         Respond ONLY with one of:\n\
         APPROVED\n\
         REJECTED: <short reason>\n\n\
         No analysis, no markdown, no explanation — just the verdict line."
    );

    info!("reviewing code");
    let result = sandbox.exec(&agent_cmd(agent, &instruction, false)).await?;
    check_exec(&result, "Review")?;

    let output = result.stdout.trim().to_string();
    for line in output.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("APPROVED") {
            return Ok(ReviewVerdict::Approved);
        }
        if trimmed.starts_with("REJECTED") {
            let feedback = output
                .split_once("REJECTED")
                .map(|x| x.1)
                .unwrap_or("")
                .trim()
                .to_string();
            return Ok(ReviewVerdict::Rejected { feedback });
        }
    }

    warn!("review output did not contain APPROVED/REJECTED");
    Ok(ReviewVerdict::InvalidFormat)
}

/// run a single validation step
pub async fn run_validate_step(
    sandbox: &mut impl Sandbox,
    step: &ValidateStep,
) -> Result<ExecResult> {
    info!(step = %step.name, command = %step.command, "running validation step");
    let result = sandbox.exec(&step.command).await?;
    debug!(
        step = %step.name,
        exit_code = result.exit_code,
        "validation step finished"
    );
    Ok(result)
}
