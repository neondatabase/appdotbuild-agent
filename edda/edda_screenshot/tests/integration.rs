use edda_screenshot::ScreenshotOptions;

#[test]
fn test_screenshot_options_default() {
    let options = ScreenshotOptions::default();
    assert_eq!(options.port, 8000);
    assert_eq!(options.wait_time_ms, 30000);
    assert_eq!(options.url, "/");
    assert_eq!(options.env_vars.len(), 0);
}

#[test]
fn test_screenshot_options_custom() {
    let options = ScreenshotOptions {
        port: 3000,
        wait_time_ms: 5000,
        url: "/health".to_string(),
        env_vars: vec![("KEY".to_string(), "VALUE".to_string())],
    };

    assert_eq!(options.port, 3000);
    assert_eq!(options.wait_time_ms, 5000);
    assert_eq!(options.url, "/health");
    assert_eq!(options.env_vars.len(), 1);
}

/// Smoke test using the trpc template from the repo
/// Run with: cargo test --features dagger test_screenshot_smoke
#[tokio::test]
#[cfg_attr(not(feature = "dagger"), ignore)]
async fn test_screenshot_smoke() {
    use edda_sandbox::dagger::ConnectOpts;
    use edda_screenshot::screenshot_app;
    use std::path::PathBuf;

    // use the trpc template from the repo
    let template_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("edda_templates")
        .join("template_trpc");

    if !template_dir.exists() {
        panic!(
            "Template not found at {}. This test expects the edda_templates crate.",
            template_dir.display()
        );
    }

    let output_dir = std::env::temp_dir().join("screenshot-smoke-test");
    std::fs::create_dir_all(&output_dir).unwrap();

    let template_dir_str = template_dir.to_string_lossy().to_string();
    let output_str = output_dir.to_string_lossy().to_string();

    println!("Template directory: {}", template_dir_str);
    println!("Output directory: {}", output_str);

    let options = ScreenshotOptions {
        port: 8000,
        wait_time_ms: 30000,
        env_vars: vec![
            ("DATABRICKS_HOST".to_string(), "https://example.databricks.com".to_string()),
            ("DATABRICKS_TOKEN".to_string(), "dummy_token_for_test".to_string()),
        ],
        ..Default::default()
    };

    ConnectOpts::default()
        .connect(|client| async move {
            let app_source = client.host().directory(&template_dir_str);

            let screenshots_dir = screenshot_app(&client, app_source, options)
                .await
                .expect("Screenshot should succeed");

            screenshots_dir
                .export(&output_str)
                .await
                .expect("Export should succeed");

            Ok(())
        })
        .await
        .expect("Dagger connection should succeed");

    let screenshot_path = output_dir.join("screenshot.png");
    let logs_path = output_dir.join("logs.txt");

    assert!(screenshot_path.exists(), "screenshot.png should exist");
    assert!(logs_path.exists(), "logs.txt should exist");

    let screenshot_size = std::fs::metadata(&screenshot_path).unwrap().len();
    assert!(screenshot_size > 1000, "Screenshot should have reasonable size");

    println!("✓ Smoke test passed");
    println!("  Screenshot: {}", screenshot_path.display());
    println!("  Logs: {}", logs_path.display());
}
