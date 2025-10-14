use dabgent_mcp::providers::{CombinedProvider, IOProvider};
use rmcp::model::CallToolRequestParam;
use rmcp::ServiceExt;
use rmcp_in_process_transport::in_process::TokioInProcess;
use std::fs;
use std::path::Path;
use tempfile::TempDir;

// helper to verify expected files in work_dir
fn verify_template_files(work_dir: &Path) {
    assert!(work_dir.exists(), "work_dir should exist");

    // verify Dockerfile exists in root
    let dockerfile = work_dir.join("Dockerfile");
    assert!(dockerfile.exists(), "Dockerfile should exist in work_dir root");

    // verify .gitignore exists in root
    let gitignore = work_dir.join(".gitignore");
    assert!(gitignore.exists(), ".gitignore should exist in work_dir root");

    // verify we have some files
    let has_files = work_dir.read_dir().unwrap().count() > 0;
    assert!(has_files, "work_dir should contain files from template");
}

#[tokio::test]
async fn test_optimistic() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path().join("optimistic_test");

    let io = IOProvider::new().unwrap();
    let provider = CombinedProvider::new(None, None, Some(io)).unwrap();
    let tokio_in_process = TokioInProcess::new(provider).await.unwrap();
    let service = ().serve(tokio_in_process).await.unwrap();

    let args = serde_json::json!({
        "work_dir": work_dir.to_string_lossy(),
        "force_rewrite": false
    });

    let result = service
        .call_tool(CallToolRequestParam {
            name: "initiate_project".into(),
            arguments: Some(args.as_object().unwrap().clone()),
        })
        .await
        .unwrap();

    // verify success message
    let content = result.content.first().unwrap();
    let text = content.as_text().unwrap();
    assert!(text.text.contains("Successfully copied"));
    assert!(text.text.contains("from default template"));

    // verify files including Dockerfile and .gitignore
    verify_template_files(&work_dir);

    service.cancel().await.unwrap();
}

#[tokio::test]
async fn test_force_rewrite() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path().join("force_rewrite_test");

    let io = IOProvider::new().unwrap();
    let provider = CombinedProvider::new(None, None, Some(io)).unwrap();
    let tokio_in_process = TokioInProcess::new(provider).await.unwrap();
    let service = ().serve(tokio_in_process).await.unwrap();

    let args = serde_json::json!({
        "work_dir": work_dir.to_string_lossy(),
        "force_rewrite": false
    });

    // initial copy
    service
        .call_tool(CallToolRequestParam {
            name: "initiate_project".into(),
            arguments: Some(args.as_object().unwrap().clone()),
        })
        .await
        .unwrap();

    // read original Dockerfile content
    let dockerfile_path = work_dir.join("Dockerfile");
    let original_dockerfile = fs::read_to_string(&dockerfile_path).unwrap();

    // mess with files: add extra file and modify Dockerfile
    fs::write(work_dir.join("extra_file.txt"), "should be deleted").unwrap();
    fs::write(&dockerfile_path, "modified content").unwrap();
    assert!(work_dir.join("extra_file.txt").exists());

    // force rewrite
    let args = serde_json::json!({
        "work_dir": work_dir.to_string_lossy(),
        "force_rewrite": true
    });

    let result = service
        .call_tool(CallToolRequestParam {
            name: "initiate_project".into(),
            arguments: Some(args.as_object().unwrap().clone()),
        })
        .await
        .unwrap();

    let content = result.content.first().unwrap();
    let text = content.as_text().unwrap();
    assert!(text.text.contains("Successfully copied"));

    // verify extra file was removed
    assert!(
        !work_dir.join("extra_file.txt").exists(),
        "extra_file.txt should be removed by force_rewrite"
    );

    // verify Dockerfile is restored to original
    let restored_dockerfile = fs::read_to_string(&dockerfile_path).unwrap();
    assert_eq!(
        original_dockerfile, restored_dockerfile,
        "Dockerfile should be restored to original content"
    );

    verify_template_files(&work_dir);

    service.cancel().await.unwrap();
}

#[tokio::test]
async fn test_pessimistic_no_write_access() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path().join("readonly_test");

    // create work_dir and make it read-only
    fs::create_dir_all(&work_dir).unwrap();

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&work_dir).unwrap().permissions();
        perms.set_mode(0o444); // read-only
        fs::set_permissions(&work_dir, perms).unwrap();
    }

    let io = IOProvider::new().unwrap();
    let provider = CombinedProvider::new(None, None, Some(io)).unwrap();
    let tokio_in_process = TokioInProcess::new(provider).await.unwrap();
    let service = ().serve(tokio_in_process).await.unwrap();

    let args = serde_json::json!({
        "work_dir": work_dir.to_string_lossy(),
        "force_rewrite": false
    });

    let result = service
        .call_tool(CallToolRequestParam {
            name: "initiate_project".into(),
            arguments: Some(args.as_object().unwrap().clone()),
        })
        .await;

    // should fail with permission error
    assert!(result.is_err(), "should fail due to permission denied");

    service.cancel().await.unwrap();

    // cleanup: restore permissions before dropping TempDir
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&work_dir).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&work_dir, perms).unwrap();
    }
}
