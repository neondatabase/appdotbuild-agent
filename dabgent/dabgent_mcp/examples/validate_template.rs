//! Example MCP client that initializes a project template and validates it
//!
//! This demonstrates:
//! - Calling initiate_project to copy template files to a work directory
//! - Calling validate_project to run TypeScript compilation checks
//!
//! Note: The template_trpc template has interdependencies between client and server,
//! so validation may fail if server dependencies aren't installed. This is expected
//! and demonstrates that the validation tool correctly detects compilation issues.
//!
//! Run with: cargo run --example validate_template

use dabgent_mcp::providers::IOProvider;
use eyre::Result;
use rmcp::model::CallToolRequestParam;
use rmcp::ServiceExt;
use rmcp_in_process_transport::in_process::TokioInProcess;
use serde_json::json;
use tempfile::TempDir;

#[tokio::main]
async fn main() -> Result<()> {
    // initialize logging if RUST_LOG is set
    if std::env::var("RUST_LOG").is_ok() {
        tracing_subscriber::fmt::init();
    }

    println!("Starting dabgent-mcp server in-process...\n");

    // create I/O provider
    let provider = IOProvider::new()?;

    // create in-process service
    let tokio_in_process = TokioInProcess::new(provider).await?;
    let service = ().serve(tokio_in_process).await?;

    println!("Connected to server!\n");

    // create temporary work directory
    let temp_dir = TempDir::new()?;
    let work_dir = temp_dir.path().to_string_lossy().to_string();
    println!("Created temporary work directory: {}\n", work_dir);

    // step 1: initialize project
    println!("=== Step 1: Initialize project from template ===");
    let init_args = json!({
        "work_dir": work_dir,
        "force_rewrite": false
    });
    let init_result = service
        .call_tool(CallToolRequestParam {
            name: "initiate_project".into(),
            arguments: Some(init_args.as_object().unwrap().clone()),
        })
        .await?;

    // display initialization result
    if let Some(content) = init_result.content.first() {
        if let Some(text) = content.as_text() {
            println!("{}", text.text);
        }
    }
    println!();

    // step 2: validate the initialized project
    println!("=== Step 2: Validate TypeScript compilation ===");
    let validate_args = json!({
        "work_dir": work_dir
    });
    let validate_result = service
        .call_tool(CallToolRequestParam {
            name: "validate_project".into(),
            arguments: Some(validate_args.as_object().unwrap().clone()),
        })
        .await?;

    // display validation result
    let validation_text = if let Some(content) = validate_result.content.first() {
        if let Some(text) = content.as_text() {
            text.text.clone()
        } else {
            String::new()
        }
    } else {
        String::new()
    };

    println!("{}", validation_text);
    println!();

    // check if validation was successful by looking at the text content
    if validation_text.contains("Validation passed") {
        println!("✅ Validation passed!");
    } else {
        println!("❌ Validation failed!");
    }

    // cleanup
    service.cancel().await?;
    println!("\nExample complete!");

    Ok(())
}
