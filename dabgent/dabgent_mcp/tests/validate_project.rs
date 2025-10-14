use dabgent_mcp::providers::{CombinedProvider, IOProvider};
use rmcp::model::CallToolRequestParam;
use rmcp::ServiceExt;
use rmcp_in_process_transport::in_process::TokioInProcess;
use tempfile::TempDir;

fn create_io_provider() -> CombinedProvider {
    let io = IOProvider::new().unwrap();
    CombinedProvider::new(None, None, Some(io)).unwrap()
}

#[tokio::test]
async fn test_validate_after_initiate() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path();

    let provider = create_io_provider();
    let tokio_in_process = TokioInProcess::new(provider).await.unwrap();
    let service = ().serve(tokio_in_process).await.unwrap();

    // initialize project
    let init_args = serde_json::json!({
        "work_dir": work_dir.to_string_lossy(),
        "force_rewrite": false
    });

    service
        .call_tool(CallToolRequestParam {
            name: "initiate_project".into(),
            arguments: Some(init_args.as_object().unwrap().clone()),
        })
        .await
        .unwrap();

    // validate the initialized project
    let validate_args = serde_json::json!({
        "work_dir": work_dir.to_string_lossy()
    });

    let validate_result = service
        .call_tool(CallToolRequestParam {
            name: "validate_project".into(),
            arguments: Some(validate_args.as_object().unwrap().clone()),
        })
        .await
        .unwrap();

    // extract validation result text
    let validation_text = validate_result
        .content
        .first()
        .and_then(|c| c.as_text())
        .map(|t| t.text.clone())
        .unwrap_or_default();

    // default template should pass validation
    assert!(
        validation_text.contains("Validation passed"),
        "default template should pass validation"
    );

    service.cancel().await.unwrap();
}

#[tokio::test]
async fn test_validate_with_typescript_error() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path();

    let provider = create_io_provider();
    let tokio_in_process = TokioInProcess::new(provider).await.unwrap();
    let service = ().serve(tokio_in_process).await.unwrap();

    // initialize project
    let init_args = serde_json::json!({
        "work_dir": work_dir.to_string_lossy(),
        "force_rewrite": false
    });

    service
        .call_tool(CallToolRequestParam {
            name: "initiate_project".into(),
            arguments: Some(init_args.as_object().unwrap().clone()),
        })
        .await
        .unwrap();

    // introduce a TypeScript syntax error
    let broken_file = work_dir.join("server/src/index.ts");
    std::fs::write(
        &broken_file,
        "const x: number = 'this is not a number'; // type error\n"
    ).unwrap();

    // validate should detect the error
    let validate_args = serde_json::json!({
        "work_dir": work_dir.to_string_lossy()
    });

    let validate_result = service
        .call_tool(CallToolRequestParam {
            name: "validate_project".into(),
            arguments: Some(validate_args.as_object().unwrap().clone()),
        })
        .await
        .unwrap();

    // extract validation result text
    let validation_text = validate_result
        .content
        .first()
        .and_then(|c| c.as_text())
        .map(|t| t.text.clone())
        .unwrap_or_default();

    // validation should fail due to type error
    assert!(
        validation_text.contains("Validation failed"),
        "validation should fail with TypeScript type error"
    );

    service.cancel().await.unwrap();
}
