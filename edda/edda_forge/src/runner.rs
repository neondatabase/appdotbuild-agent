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
pub async fn rewrite_task(sandbox: &mut impl Sandbox, prompt: &str) -> Result<String> {
    let instruction = format!(
        "You are working in /app, a Rust library project. \
         The user wants: {prompt}\n\n\
         Create a file called /app/tasks.md that breaks this down into a clear, \
         numbered task list for implementing this as a Rust library. \
         Focus on the public API, data structures, and key algorithms. \
         Do NOT write any Rust code yet — only the task list."
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
    error_context: Option<&str>,
) -> Result<()> {
    let mut instruction = format!(
        "You are working in /app, a Rust library project. \
         Here is the task list:\n\n{task_list}\n\n\
         Write comprehensive tests in /app/tests/integration.rs that verify the \
         public API described in the task list. \
         Write ONLY tests — do not implement the library code. \
         The tests should use the crate name `forge_project`. \
         Make sure the test file compiles on its own (all necessary imports, etc.), \
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
    context: Option<&str>,
) -> Result<()> {
    let tests = sandbox.read_file("/app/tests/integration.rs").await?;

    let mut instruction = format!(
        "You are working in /app, a Rust library project. \
         Here is the task list:\n\n{task_list}\n\n\
         Here are the tests that must pass:\n\n```rust\n{tests}\n```\n\n\
         Implement the library in /app/src/lib.rs so that all tests pass. \
         You may create additional modules under /app/src/ if needed. \
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
}

/// ask Claude to review the implementation
pub async fn review(sandbox: &mut impl Sandbox, task_list: &str) -> Result<ReviewVerdict> {
    let source = sandbox.read_file("/app/src/lib.rs").await?;
    let tests = sandbox.read_file("/app/tests/integration.rs").await?;

    let instruction = format!(
        "You are a senior Rust code reviewer. \
         Review the following implementation against the task list and tests.\n\n\
         Task list:\n{task_list}\n\n\
         Implementation:\n```rust\n{source}\n```\n\n\
         Tests:\n```rust\n{tests}\n```\n\n\
         Check for: correctness, idiomatic Rust, error handling, edge cases, API design.\n\n\
         You MUST respond with exactly one of:\n\
         - First line: APPROVED (if the code is acceptable)\n\
         - First line: REJECTED (if changes are needed), followed by specific feedback on what to fix\n\n\
         Do NOT write or modify any files. Only output your verdict."
    );

    info!("reviewing code");
    let result = sandbox.exec(&claude_exec(&instruction)).await?;
    check_exec(&result, "Review")?;

    let output = result.stdout.trim().to_string();
    if output.starts_with("APPROVED") {
        Ok(ReviewVerdict::Approved)
    } else if output.starts_with("REJECTED") {
        let feedback = output
            .strip_prefix("REJECTED")
            .unwrap_or(&output)
            .trim()
            .to_string();
        Ok(ReviewVerdict::Rejected { feedback })
    } else {
        // if the model didn't follow the format strictly, treat as rejection with full output as feedback
        warn!("review output did not start with APPROVED/REJECTED, treating as rejection");
        Ok(ReviewVerdict::Rejected { feedback: output })
    }
}

/// run cargo check
pub async fn cargo_check(sandbox: &mut impl Sandbox) -> Result<ExecResult> {
    info!("running cargo check");
    let result = sandbox.exec("cargo check 2>&1").await?;
    debug!(exit_code = result.exit_code, "cargo check finished");
    Ok(result)
}

/// run cargo test
pub async fn run_tests(sandbox: &mut impl Sandbox) -> Result<ExecResult> {
    info!("running cargo test");
    let result = sandbox.exec("cargo test 2>&1").await?;
    debug!(exit_code = result.exit_code, "cargo test finished");
    Ok(result)
}

/// run cargo bench (non-fatal — we just log the output)
pub async fn run_benchmark(sandbox: &mut impl Sandbox) -> Result<ExecResult> {
    info!("running cargo bench");
    let result = sandbox.exec("cargo bench 2>&1").await?;
    debug!(exit_code = result.exit_code, "cargo bench finished");
    Ok(result)
}
