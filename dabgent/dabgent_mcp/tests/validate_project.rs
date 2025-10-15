use dabgent_mcp::providers::{IOProvider, Template};
use std::path::Path;
use tempfile::TempDir;

fn initiate_project_for_tests(work_dir: &Path, force_rewrite: bool) {
    IOProvider::initiate_project_impl(work_dir, Template::Trpc, force_rewrite).unwrap();
}

#[tokio::test]
async fn test_validate_after_initiate() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path();

    // initialize project
    initiate_project_for_tests(work_dir, false);

    // validate the initialized project (build + tests)
    let result = IOProvider::validate_project_impl(work_dir).await.unwrap();

    // default template should pass validation (including healthcheck test)
    assert!(
        result.success,
        "default template should pass validation (build + tests). Details: {:?}",
        result.details
    );
    assert!(result.details.is_none());
    assert!(result.message.contains("build + tests"));
}

#[tokio::test]
async fn test_validate_with_typescript_error() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path();

    // initialize project
    initiate_project_for_tests(work_dir, false);

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

#[tokio::test]
async fn test_validate_with_failing_test() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path();

    // initialize project
    initiate_project_for_tests(work_dir, false);

    // break the test file itself to make test fail
    let test_file = work_dir.join("server/src/healthcheck.test.ts");
    let content = std::fs::read_to_string(&test_file).unwrap();
    let modified = content.replace(
        r#"assert.equal(result.status, "ok");"#,
        r#"assert.equal(result.status, "broken");"#
    );
    std::fs::write(&test_file, modified).unwrap();

    // validate should detect the test failure
    let result = IOProvider::validate_project_impl(work_dir).await.unwrap();

    // validation should fail due to test failure
    assert!(!result.success, "validation should fail when tests fail");
    assert!(result.details.is_some());
}
