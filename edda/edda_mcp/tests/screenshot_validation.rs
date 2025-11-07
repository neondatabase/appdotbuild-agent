use edda_mcp::providers::IOProvider;
use edda_mcp::providers::io::validation::{Validation, ValidationTRPC};
use edda_mcp::config::ScreenshotConfig;
use edda_templates::TemplateTRPC;
use std::path::Path;
use tempfile::TempDir;

fn initiate_project_for_tests(work_dir: &Path, force_rewrite: bool) {
    IOProvider::initiate_project_impl(work_dir, TemplateTRPC, force_rewrite).unwrap();
}

#[tokio::test]
#[cfg_attr(not(feature = "dagger"), ignore)]
async fn test_screenshot_capture_success() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path();

    // initialize project with Dockerfile
    initiate_project_for_tests(work_dir, false);

    // validate with screenshot enabled
    let validation_strategy = ValidationTRPC.boxed();
    let screenshot_config = Some(ScreenshotConfig {
        enabled: Some(true),
        url: None,
        port: None,
        wait_time_ms: None,
    });

    let result = IOProvider::validate_project_impl(work_dir, validation_strategy, screenshot_config)
        .await
        .unwrap();

    // validation should pass
    assert!(
        result.success,
        "validation should pass with screenshot enabled"
    );

    // screenshot should be captured
    assert!(
        result.screenshot_path.is_some(),
        "screenshot_path should be present when Dockerfile exists"
    );

    // verify screenshot file exists and has content
    if let Some(screenshot_path) = &result.screenshot_path {
        let screenshot_file = Path::new(screenshot_path);
        assert!(
            screenshot_file.exists(),
            "screenshot file should exist at {}",
            screenshot_path
        );

        let metadata = std::fs::metadata(screenshot_file).unwrap();
        assert!(
            metadata.len() > 0,
            "screenshot file should have content (size > 0)"
        );
    }
}

#[tokio::test]
#[cfg_attr(not(feature = "dagger"), ignore)]
async fn test_screenshot_failure_missing_dockerfile() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path();

    // initialize project
    initiate_project_for_tests(work_dir, false);

    // delete Dockerfile to simulate missing Dockerfile
    let dockerfile = work_dir.join("Dockerfile");
    std::fs::remove_file(&dockerfile).unwrap();
    assert!(!dockerfile.exists(), "Dockerfile should be deleted");

    // validate with screenshot enabled
    let validation_strategy = ValidationTRPC.boxed();
    let screenshot_config = Some(ScreenshotConfig {
        enabled: Some(true),
        url: None,
        port: None,
        wait_time_ms: None,
    });

    let result = IOProvider::validate_project_impl(work_dir, validation_strategy, screenshot_config)
        .await
        .unwrap();

    // validation should still pass (screenshot is non-blocking)
    assert!(
        result.success,
        "validation should pass even when screenshot fails (soft failure)"
    );

    // screenshot should not be captured
    assert!(
        result.screenshot_path.is_none(),
        "screenshot_path should be None when Dockerfile is missing"
    );

    // browser_logs should contain error about missing Dockerfile
    assert!(
        result.browser_logs.is_some(),
        "browser_logs should contain error message"
    );

    if let Some(logs) = &result.browser_logs {
        assert!(
            logs.contains("Dockerfile"),
            "error message should mention Dockerfile. Got: {}",
            logs
        );
    }
}
