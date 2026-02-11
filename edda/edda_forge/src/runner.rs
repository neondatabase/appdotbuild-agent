use crate::config::ValidateStep;
use edda_sandbox::{ExecResult, Sandbox};
use eyre::{Result, bail};
use tracing::{debug, info, warn};

const CLAUDE_CMD: &str = "claude -p";
const CLAUDE_FLAGS: &str = "--dangerously-skip-permissions";

fn claude_exec(prompt: &str) -> String {
    // escape single quotes in prompt for shell safety
    let escaped = prompt.replace('\'', "'\\''");
    format!("{CLAUDE_CMD} '{escaped}' {CLAUDE_FLAGS}")
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
    if s.len() <= max {
        s
    } else {
        &s[..max]
    }
}

/// ask Claude to decompose the prompt into a task list (tasks.md)
pub async fn rewrite_task(
    sandbox: &mut impl Sandbox,
    prompt: &str,
    language: &str,
) -> Result<String> {
    let instruction = format!(
        "You are working in /app, a {language} project. \
         The user wants: {prompt}\n\n\
         Create a file called /app/tasks.md that breaks this down into a clear, \
         numbered task list for implementing this as a {language} library. \
         Focus on the public API, data structures, and key algorithms. \
         Do NOT write any code yet — only the task list."
    );

    info!("rewriting task into tasks.md");
    let result = sandbox.exec(&claude_exec(&instruction)).await?;
    check_exec(&result, "RewriteTask")?;

    let task_list = sandbox.read_file("/app/tasks.md").await?;
    if task_list.trim().is_empty() {
        bail!("RewriteTask produced empty tasks.md");
    }
    debug!(task_list_len = task_list.len(), "tasks.md created");
    Ok(task_list)
}

/// ask Claude to write tests based on the task list
pub async fn write_tests(
    sandbox: &mut impl Sandbox,
    task_list: &str,
    language: &str,
    error_context: Option<&str>,
) -> Result<()> {
    let mut instruction = format!(
        "You are working in /app, a {language} project. \
         Here is the task list:\n\n{task_list}\n\n\
         Write comprehensive tests that verify the public API described in the task list. \
         Write ONLY tests — do not implement the library code. \
         Place tests in the conventional location for a {language} project. \
         Make sure the test files compile/parse on their own (all necessary imports, etc.), \
         though tests will fail until the code is implemented."
    );

    if let Some(ctx) = error_context {
        instruction.push_str(&format!(
            "\n\nPrevious attempt failed with this error — fix the issues:\n{ctx}"
        ));
    }

    info!("writing tests");
    let result = sandbox.exec(&claude_exec(&instruction)).await?;
    check_exec(&result, "WriteTests")?;
    Ok(())
}

/// ask Claude to implement the code
pub async fn write_code(
    sandbox: &mut impl Sandbox,
    task_list: &str,
    language: &str,
    context: Option<&str>,
) -> Result<()> {
    let mut instruction = format!(
        "You are working in /app, a {language} project. \
         Here is the task list:\n\n{task_list}\n\n\
         Read the existing test files in the project to understand what must pass. \
         Implement the library so that all tests pass. \
         You may create additional modules/files as needed. \
         Focus on correctness — make all tests pass."
    );

    if let Some(ctx) = context {
        instruction.push_str(&format!(
            "\n\nPrevious attempt failed with this error — fix the issues:\n{ctx}"
        ));
    }

    info!("writing code");
    let result = sandbox.exec(&claude_exec(&instruction)).await?;
    check_exec(&result, "WriteCode")?;
    Ok(())
}

pub enum ReviewVerdict {
    Approved,
    Rejected { feedback: String },
    InvalidFormat,
}

/// ask Claude to review the diff
pub async fn review(sandbox: &mut impl Sandbox, task_list: &str, language: &str) -> Result<ReviewVerdict> {
    let diff_result = sandbox.exec("git add -A && git diff --cached").await?;
    let diff = if diff_result.exit_code == 0 {
        diff_result.stdout
    } else {
        warn!("git diff failed during review, falling back to file inspection");
        String::new()
    };

    let verdict_format = "\n\nRespond ONLY with one of:\n\
         APPROVED\n\
         REJECTED: <short reason>\n\n\
         No analysis, no markdown, no explanation — just the verdict line.";

    let instruction = if diff.is_empty() {
        format!(
            "You are a {language} code reviewer. \
             You are working in /app. Read the source code yourself.\n\n\
             Task list:\n{task_list}\n\n\
             Check for correctness and bugs only. Do NOT write or modify any files.{verdict_format}"
        )
    } else {
        format!(
            "You are a {language} code reviewer. Review this diff.\n\n\
             Task list:\n{task_list}\n\n\
             Diff:\n```diff\n{diff}\n```\n\n\
             Check for correctness and bugs only. Do NOT write or modify any files.{verdict_format}"
        )
    };

    info!("reviewing code");
    let result = sandbox.exec(&claude_exec(&instruction)).await?;
    check_exec(&result, "Review")?;

    let output = result.stdout.trim().to_string();
    // scan lines for verdict — model doesn't always put it on the first line
    for line in output.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("APPROVED") {
            return Ok(ReviewVerdict::Approved);
        }
        if trimmed.starts_with("REJECTED") {
            let feedback = output.split_once("REJECTED").map(|x| x.1)
                .unwrap_or("")
                .trim()
                .to_string();
            return Ok(ReviewVerdict::Rejected { feedback });
        }
    }

    // no explicit verdict found — invalid format, should retry review itself
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
