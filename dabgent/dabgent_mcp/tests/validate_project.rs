use dabgent_mcp::providers::IOProvider;
use tempfile::TempDir;

#[tokio::test]
async fn test_validate_after_initiate() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path();

    // initialize project
    IOProvider::initiate_project_impl(work_dir, false).unwrap();

    // validate the initialized project
    let result = IOProvider::validate_project_impl(work_dir).await.unwrap();

    // default template should pass validation
    assert!(result.success, "default template should pass validation");
    assert!(result.details.is_none());
}

#[tokio::test]
async fn test_validate_with_typescript_error() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path();

    // initialize project
    IOProvider::initiate_project_impl(work_dir, false).unwrap();

    // introduce a TypeScript syntax error
    let broken_file = work_dir.join("server/src/index.ts");
    std::fs::write(
        &broken_file,
        "const x: number = 'this is not a number'; // type error\n"
    ).unwrap();

    // validate should detect the error
    let result = IOProvider::validate_project_impl(work_dir).await.unwrap();

    // validation should fail due to type error
    assert!(!result.success, "validation should fail with TypeScript type error");
    assert!(result.details.is_some());
}
