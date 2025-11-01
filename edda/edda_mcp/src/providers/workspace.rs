use crate::session::SessionContext;
use eyre::{eyre, Result};
use rmcp::handler::server::router::tool::ToolRouter;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{CallToolResult, Content, ServerInfo};
use rmcp::{ErrorData, ServerHandler, tool, tool_handler, tool_router};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use tokio::process::Command;

/// validates that file_path is within base_dir to prevent directory traversal
fn validate_path(base_dir: &Path, file_path: &str) -> Result<PathBuf> {
    let base = base_dir.canonicalize()?;
    let target = base.join(file_path);

    // resolve symlinks and check if within base
    let resolved = match target.canonicalize() {
        Ok(p) => p,
        Err(_) => {
            // if file doesn't exist yet, check parent directory
            if let Some(parent) = target.parent() {
                if parent.exists() {
                    let parent_canonical = parent.canonicalize()?;
                    if !parent_canonical.starts_with(&base) {
                        return Err(eyre!("Access denied: path outside base directory"));
                    }
                    target
                } else {
                    return Err(eyre!("Parent directory does not exist"));
                }
            } else {
                return Err(eyre!("Invalid path"));
            }
        }
    };

    if !resolved.starts_with(&base) {
        return Err(eyre!("Access denied: path outside base directory"));
    }

    Ok(resolved)
}

/// WorkspaceTools provides file operation tools scoped to a session's workspace directory.
/// These tools are similar to Claude Code's base toolkit, enabling file I/O, bash execution,
/// and code search within the project boundaries.
#[derive(Debug, Clone)]
pub struct WorkspaceTools {
    session_ctx: SessionContext,
    tool_router: ToolRouter<Self>,
}

impl WorkspaceTools {
    pub fn new(session_ctx: SessionContext) -> Result<Self> {
        Ok(Self {
            session_ctx,
            tool_router: Self::tool_router(),
        })
    }

    async fn get_work_dir(&self) -> Result<PathBuf, ErrorData> {
        let work_dir = self.session_ctx.work_dir.read().await;
        match work_dir.as_ref() {
            Some(dir) => Ok(dir.clone()),
            None => Err(ErrorData::invalid_request(
                "Workspace directory not set. Please run scaffold_data_app first to initialize your project.".to_string(),
                None,
            )),
        }
    }
}

// read_file tool
#[derive(Debug, Deserialize, JsonSchema, Serialize)]
struct ReadFileArgs {
    /// Path to file (relative to base directory)
    file_path: String,
    /// Line number to start reading from (1-indexed)
    #[serde(default)]
    offset: Option<usize>,
    /// Number of lines to read (default: 2000)
    #[serde(default)]
    limit: Option<usize>,
}

// write_file tool
#[derive(Debug, Deserialize, JsonSchema, Serialize)]
struct WriteFileArgs {
    /// Path to file (relative to base directory)
    file_path: String,
    /// Content to write
    content: String,
}

// edit_file tool
#[derive(Debug, Deserialize, JsonSchema, Serialize)]
struct EditFileArgs {
    /// Path to file (relative to base directory)
    file_path: String,
    /// Exact string to replace (must match exactly including whitespace)
    old_string: String,
    /// Replacement string (must differ from old_string)
    new_string: String,
    /// Replace all occurrences (default: false)
    #[serde(default)]
    replace_all: bool,
}

// bash tool
#[derive(Debug, Deserialize, JsonSchema, Serialize)]
struct BashArgs {
    /// Command to execute. Always quote paths with spaces.
    command: String,
    /// 5-10 word description of what command does
    #[serde(default)]
    description: Option<String>,
    /// Timeout in milliseconds (default: 120000ms)
    #[serde(default)]
    timeout: Option<u64>,
}

// grep tool
#[derive(Debug, Deserialize, JsonSchema, Serialize)]
struct GrepArgs {
    /// Regex pattern to search for
    pattern: String,
    /// File or directory to search (relative to base directory)
    #[serde(default)]
    path: Option<String>,
    /// Case insensitive search (default: false)
    #[serde(default)]
    case_insensitive: bool,
    /// Limit output to first N matches
    #[serde(default)]
    head_limit: Option<usize>,
}

// glob tool
#[derive(Debug, Deserialize, JsonSchema, Serialize)]
struct GlobArgs {
    /// Glob pattern (e.g., '**/*.ts')
    pattern: String,
}

#[tool_router]
impl WorkspaceTools {
    #[tool(
        name = "read_file",
        description = "Read file contents with line numbers. Default: reads up to 2000 lines from beginning. Lines >2000 chars truncated."
    )]
    pub async fn read_file(
        &self,
        Parameters(args): Parameters<ReadFileArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let base_dir = self.get_work_dir().await?;
        let path = validate_path(&base_dir, &args.file_path)
            .map_err(|e| ErrorData::invalid_params(e.to_string(), None))?;

        let content = tokio::fs::read_to_string(&path)
            .await
            .map_err(|e| ErrorData::internal_error(format!("Failed to read file: {}", e), None))?;

        let lines: Vec<&str> = content.lines().collect();

        let offset = args.offset.unwrap_or(1).saturating_sub(1);
        let limit = args.limit.unwrap_or(2000);
        let end = (offset + limit).min(lines.len());

        let selected_lines: Vec<String> = lines[offset..end]
            .iter()
            .enumerate()
            .map(|(i, line)| {
                let line_num = offset + i + 1;
                let truncated = if line.len() > 2000 {
                    &line[..2000]
                } else {
                    line
                };
                format!("{:6}\t{}", line_num, truncated)
            })
            .collect();

        Ok(CallToolResult::success(vec![Content::text(
            selected_lines.join("\n"),
        )]))
    }

    #[tool(name = "write_file", description = "Write content to a file")]
    pub async fn write_file(
        &self,
        Parameters(args): Parameters<WriteFileArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let base_dir = self.get_work_dir().await?;
        let path = validate_path(&base_dir, &args.file_path)
            .map_err(|e| ErrorData::invalid_params(e.to_string(), None))?;

        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent)
                .await
                .map_err(|e| {
                    ErrorData::internal_error(format!("Failed to create parent directory: {}", e), None)
                })?;
        }

        tokio::fs::write(&path, &args.content).await.map_err(|e| {
            ErrorData::internal_error(format!("Failed to write file: {}", e), None)
        })?;

        Ok(CallToolResult::success(vec![Content::text(format!(
            "Successfully wrote {} bytes to {}",
            args.content.len(),
            args.file_path
        ))]))
    }

    #[tool(
        name = "edit_file",
        description = "Edit file by replacing old_string with new_string. Fails if old_string not unique unless replace_all=true."
    )]
    pub async fn edit_file(
        &self,
        Parameters(args): Parameters<EditFileArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        if args.old_string == args.new_string {
            return Err(ErrorData::invalid_params(
                "old_string and new_string must be different".to_string(),
                None,
            ));
        }

        let base_dir = self.get_work_dir().await?;
        let path = validate_path(&base_dir, &args.file_path)
            .map_err(|e| ErrorData::invalid_params(e.to_string(), None))?;

        let content = tokio::fs::read_to_string(&path)
            .await
            .map_err(|e| ErrorData::internal_error(format!("Failed to read file: {}", e), None))?;

        let count = content.matches(&args.old_string).count();

        if count == 0 {
            return Err(ErrorData::invalid_params(
                format!("old_string not found in {}", args.file_path),
                None,
            ));
        }

        if !args.replace_all && count > 1 {
            return Err(ErrorData::invalid_params(
                format!(
                    "old_string appears {} times in {}. Use replace_all=true or provide more context.",
                    count, args.file_path
                ),
                None,
            ));
        }

        let new_content = content.replace(&args.old_string, &args.new_string);
        tokio::fs::write(&path, new_content).await.map_err(|e| {
            ErrorData::internal_error(format!("Failed to write file: {}", e), None)
        })?;

        let occurrences = if args.replace_all { "all" } else { "1" };
        Ok(CallToolResult::success(vec![Content::text(format!(
            "Successfully replaced {} occurrence(s) in {}",
            occurrences, args.file_path
        ))]))
    }

    #[tool(
        name = "bash",
        description = "Execute bash command in workspace directory. Use for terminal operations (npm, git, etc). Output truncated at 30000 chars."
    )]
    pub async fn bash(
        &self,
        Parameters(args): Parameters<BashArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let base_dir = self.get_work_dir().await?;
        let timeout_ms = args.timeout.unwrap_or(120000);
        let timeout_duration = tokio::time::Duration::from_millis(timeout_ms);

        let child = Command::new("sh")
            .arg("-c")
            .arg(&args.command)
            .current_dir(&base_dir)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| ErrorData::internal_error(format!("Failed to spawn command: {}", e), None))?;

        let output = tokio::time::timeout(timeout_duration, child.wait_with_output())
            .await
            .map_err(|_| {
                ErrorData::internal_error(format!("Command timed out after {}ms", timeout_ms), None)
            })?
            .map_err(|e| {
                ErrorData::internal_error(format!("Failed to execute command: {}", e), None)
            })?;

        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        let combined = format!("{}{}", stdout, stderr);

        let result = if combined.len() > 30000 {
            format!(
                "{}\n[Output truncated at 30000 characters]",
                &combined[..30000]
            )
        } else if combined.is_empty() {
            format!(
                "Command executed (exit code: {})",
                output.status.code().unwrap_or(-1)
            )
        } else {
            combined.to_string()
        };

        Ok(CallToolResult::success(vec![Content::text(result)]))
    }

    #[tool(
        name = "grep",
        description = "Search file contents with regex. Returns file:line:content by default. Limit results with head_limit."
    )]
    pub async fn grep(
        &self,
        Parameters(args): Parameters<GrepArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let base_dir = self.get_work_dir().await?;
        let search_path = args.path.as_deref().unwrap_or(".");
        let path = validate_path(&base_dir, search_path)
            .map_err(|e| ErrorData::invalid_params(e.to_string(), None))?;

        let regex = if args.case_insensitive {
            regex::RegexBuilder::new(&args.pattern)
                .case_insensitive(true)
                .build()
        } else {
            regex::Regex::new(&args.pattern)
        }
        .map_err(|e| ErrorData::invalid_params(format!("Invalid regex pattern: {}", e), None))?;

        let mut matches = Vec::new();
        let mut files_to_search = Vec::new();

        if path.is_file() {
            files_to_search.push(path);
        } else if path.is_dir() {
            for entry in walkdir::WalkDir::new(&path)
                .into_iter()
                .filter_map(|e| e.ok())
                .filter(|e| e.file_type().is_file())
            {
                files_to_search.push(entry.path().to_path_buf());
            }
        }

        for file in files_to_search {
            if let Ok(content) = tokio::fs::read_to_string(&file).await {
                for (line_num, line) in content.lines().enumerate() {
                    if regex.is_match(line) {
                        let rel_path = file
                            .strip_prefix(&base_dir)
                            .unwrap_or(&file)
                            .display();
                        matches.push(format!("{}:{}: {}", rel_path, line_num + 1, line));

                        if let Some(limit) = args.head_limit {
                            if matches.len() >= limit {
                                return Ok(CallToolResult::success(vec![Content::text(
                                    matches.join("\n"),
                                )]));
                            }
                        }
                    }
                }
            }
            // silently skip files that can't be read (e.g., binary files)
        }

        let result = if matches.is_empty() {
            "No matches found".to_string()
        } else {
            matches.join("\n")
        };

        Ok(CallToolResult::success(vec![Content::text(result)]))
    }

    #[tool(name = "glob", description = "Find files matching a glob pattern")]
    pub async fn glob(
        &self,
        Parameters(args): Parameters<GlobArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let base_dir = self.get_work_dir().await?;
        let pattern_path = base_dir.join(&args.pattern);
        let pattern_str = pattern_path
            .to_str()
            .ok_or_else(|| ErrorData::invalid_params("Invalid pattern path".to_string(), None))?;

        let mut matches: Vec<String> = glob::glob(pattern_str)
            .map_err(|e| ErrorData::invalid_params(format!("Invalid glob pattern: {}", e), None))?
            .filter_map(|entry| entry.ok())
            .filter_map(|path| {
                path.strip_prefix(&base_dir)
                    .ok()
                    .map(|p| p.display().to_string())
            })
            .collect();

        let result = if matches.is_empty() {
            "No files matched pattern".to_string()
        } else {
            matches.sort();
            matches.join("\n")
        };

        Ok(CallToolResult::success(vec![Content::text(result)]))
    }
}

// Internal ServerHandler impl for routing by CombinedProvider
#[tool_handler]
impl ServerHandler for WorkspaceTools {
    fn get_info(&self) -> ServerInfo {
        crate::mcp_helpers::internal_server_info()
    }
}
