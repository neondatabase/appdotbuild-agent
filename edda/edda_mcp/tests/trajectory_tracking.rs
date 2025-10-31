use edda_mcp::providers::{CombinedProvider, IOProvider};
use edda_mcp::trajectory::{TrajectoryEntry, TrajectoryTrackingProvider};
use eyre::Result;
use rmcp::ServiceExt;
use rmcp::model::CallToolRequestParam;
use rmcp_in_process_transport::in_process::TokioInProcess;
use std::fs;
use tempfile::TempDir;

#[tokio::test]
async fn test_trajectory_tracking_records_tool_calls() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let history_path = temp_dir.path().join("history.jsonl");

    let io = IOProvider::new(None)?;
    let provider = CombinedProvider::new(None, None, None, Some(io))?;

    let session_id = "test-session-123".to_string();
    let tracking_provider = TrajectoryTrackingProvider::new_with_path(
        provider,
        session_id.clone(),
        history_path.clone(),
    )?;

    let tokio_in_process = TokioInProcess::new(tracking_provider).await?;
    let service = ().serve(tokio_in_process).await?;

    // call a tool
    let work_dir = temp_dir.path().join("test_project");
    let args_json = serde_json::json!({
        "work_dir": work_dir.to_str().unwrap(),
        "force_rewrite": false
    });
    let args_map = args_json.as_object().unwrap().clone();

    let result = service
        .call_tool(CallToolRequestParam {
            name: "scaffold_data_app".into(),
            arguments: Some(args_map),
        })
        .await;

    // tool call should succeed or fail - either way it should be recorded
    if let Err(ref e) = result {
        eprintln!("Tool call failed (expected for test): {:?}", e);
    }

    // verify history.jsonl exists
    assert!(history_path.exists(), "history.jsonl should be created");

    // read and parse history entries
    let content = fs::read_to_string(&history_path)?;
    let lines: Vec<&str> = content.lines().collect();
    assert!(!lines.is_empty(), "Should have at least one entry");

    // parse first entry
    let entry: TrajectoryEntry = serde_json::from_str(lines[0])?;
    assert_eq!(entry.session_id, session_id);
    assert_eq!(entry.tool_name, "scaffold_data_app");
    assert!(entry.arguments.is_some());

    service.cancel().await?;

    Ok(())
}

#[tokio::test]
async fn test_trajectory_tracking_multiple_calls() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let history_path = temp_dir.path().join("history.jsonl");

    let io = IOProvider::new(None)?;
    let provider = CombinedProvider::new(None, None, None, Some(io))?;
    let tracking_provider = TrajectoryTrackingProvider::new_with_path(
        provider,
        "multi-test".to_string(),
        history_path.clone(),
    )?;

    let tokio_in_process = TokioInProcess::new(tracking_provider).await?;
    let service = ().serve(tokio_in_process).await?;

    // make multiple tool calls
    for i in 0..3 {
        let work_dir = temp_dir.path().join(format!("project_{}", i));
        let args_json = serde_json::json!({
            "work_dir": work_dir.to_str().unwrap(),
            "force_rewrite": false
        });
        let args_map = args_json.as_object().unwrap().clone();

        let _ = service
            .call_tool(CallToolRequestParam {
                name: "scaffold_data_app".into(),
                arguments: Some(args_map),
            })
            .await;
    }

    // verify multiple entries
    let content = fs::read_to_string(&history_path)?;
    let line_count = content.lines().count();

    assert_eq!(line_count, 3, "Should have 3 entries");

    // verify all lines are valid JSON
    assert!(
        content
            .lines()
            .all(|line| { serde_json::from_str::<TrajectoryEntry>(line).is_ok() }),
        "All lines should be valid TrajectoryEntry JSON"
    );

    service.cancel().await?;

    Ok(())
}

#[tokio::test]
async fn test_trajectory_entry_format() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let history_path = temp_dir.path().join("history.jsonl");

    let io = IOProvider::new(None)?;
    let provider = CombinedProvider::new(None, None, None, Some(io))?;
    let tracking_provider = TrajectoryTrackingProvider::new_with_path(
        provider,
        "format-test".to_string(),
        history_path.clone(),
    )?;

    let tokio_in_process = TokioInProcess::new(tracking_provider).await?;
    let service = ().serve(tokio_in_process).await?;

    // call a tool with arguments
    let work_dir = temp_dir.path().join("app");
    let args_json = serde_json::json!({
        "work_dir": work_dir.to_str().unwrap(),
        "force_rewrite": false
    });
    let args_map = args_json.as_object().unwrap().clone();

    let _result = service
        .call_tool(CallToolRequestParam {
            name: "scaffold_data_app".into(),
            arguments: Some(args_map),
        })
        .await;

    // verify entry structure
    let content = fs::read_to_string(&history_path)?;
    let entry: TrajectoryEntry = serde_json::from_str(content.lines().next().unwrap())?;

    // verify all fields
    assert!(!entry.session_id.is_empty());
    assert!(!entry.timestamp.is_empty());
    assert_eq!(entry.tool_name, "scaffold_data_app");
    assert!(entry.arguments.is_some());

    // verify timestamp is ISO 8601
    assert!(
        chrono::DateTime::parse_from_rfc3339(&entry.timestamp).is_ok(),
        "Timestamp should be valid ISO 8601"
    );

    service.cancel().await?;

    Ok(())
}

#[tokio::test]
async fn test_trajectory_tracking_error_case() -> Result<()> {
    let temp_dir = TempDir::new()?;
    let history_path = temp_dir.path().join("history.jsonl");

    let io = IOProvider::new(None)?;
    let provider = CombinedProvider::new(None, None, None, Some(io))?;
    let tracking_provider = TrajectoryTrackingProvider::new_with_path(
        provider,
        "error-test".to_string(),
        history_path.clone(),
    )?;

    let tokio_in_process = TokioInProcess::new(tracking_provider).await?;
    let service = ().serve(tokio_in_process).await?;

    // call a tool with invalid arguments (relative path should fail)
    let args_json = serde_json::json!({
        "work_dir": "relative/path",
        "force_rewrite": false
    });
    let args_map = args_json.as_object().unwrap().clone();

    let _result = service
        .call_tool(CallToolRequestParam {
            name: "scaffold_data_app".into(),
            arguments: Some(args_map),
        })
        .await;

    // verify error is recorded in history
    let content = fs::read_to_string(&history_path)?;
    let entry: TrajectoryEntry = serde_json::from_str(content.lines().next().unwrap())?;

    // error case should have success=false and error field populated
    assert!(!entry.success);
    assert!(entry.error.is_some());

    service.cancel().await?;

    Ok(())
}
