use crate::config::ValidateStep;
use edda_sandbox::{ExecResult, Sandbox};
use eyre::{Result, bail};
use tracing::{debug, info, warn};

const CLAUDE_FLAGS: &str = "--dangerously-skip-permissions";
fn claude_cmd(prompt: &str) -> String {
    let escaped = prompt.replace('\'', "'\\''");
    format!("claude -p '{escaped}' {CLAUDE_FLAGS}")
}

fn check_exec(result: &ExecResult, step: &str) -> Result<()> {
    if result.exit_code != 0 {
        warn!(
            step,
            exit_code = result.exit_code,
            stderr_len = result.stderr.len(),
            "step failed"
        );
        bail!(
            "{step} failed (exit {}): {}",
            result.exit_code,
            truncate(&result.stderr, 2000)
        );
    }
    Ok(())
}

fn truncate(s: &str, max: usize) -> &str {
    match s.get(..max) {
        Some(prefix) => prefix,
        None => s,
    }
}

/// ask Claude to decompose the prompt into a checkbox task list (tasks.md)
pub async fn plan(
    sandbox: &mut impl Sandbox,
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
    let result = sandbox.exec(&claude_cmd(&instruction)).await?;
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

/// ask Claude to work on unchecked tasks and check them off
pub async fn work(sandbox: &mut impl Sandbox, language: &str) -> Result<()> {
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
    let result = sandbox.exec(&claude_cmd(&instruction)).await?;
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

/// ask Claude to review the diff
pub async fn review(sandbox: &mut impl Sandbox, language: &str, diff_pathspec: &str) -> Result<ReviewVerdict> {
    let task_list = match read_tasks(sandbox).await {
        Ok(tasks) => tasks,
        Err(e) => {
            warn!("could not read tasks.md for review context: {e}");
            String::new()
        }
    };
    // stage all changes so Claude can inspect via `git diff --cached`
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
    let result = sandbox.exec(&claude_cmd(&instruction)).await?;
    debug!(
        stdout_len = result.stdout.len(),
        stderr_len = result.stderr.len(),
        exit_code = result.exit_code,
        stdout_head = %truncate(&result.stdout, 500),
        stderr_head = %truncate(&result.stderr, 500),
        "review raw output"
    );
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
