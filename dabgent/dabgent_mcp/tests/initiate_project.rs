use dabgent_mcp::providers::IOProvider;
use std::fs;
use std::path::Path;
use tempfile::TempDir;

// helper to verify expected files in work_dir
fn verify_template_files(work_dir: &Path) {
    assert!(work_dir.exists(), "work_dir should exist");

    // verify .gitignore exists in root
    let gitignore = work_dir.join(".gitignore");
    assert!(gitignore.exists(), ".gitignore should exist in work_dir root");

    // verify build.sh exists in root
    let build_sh = work_dir.join("build.sh");
    assert!(build_sh.exists(), "build.sh should exist in work_dir root");

    // verify client directory exists
    let client_dir = work_dir.join("client");
    assert!(client_dir.exists(), "client directory should exist");

    // verify server directory exists
    let server_dir = work_dir.join("server");
    assert!(server_dir.exists(), "server directory should exist");

    // verify we have some files
    let has_files = work_dir.read_dir().unwrap().count() > 0;
    assert!(has_files, "work_dir should contain files from template");
}

#[test]
fn test_optimistic() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path().join("optimistic_test");

    let result = IOProvider::initiate_project_impl(&work_dir, false).unwrap();

    // verify result
    assert!(result.files_copied > 0);
    assert_eq!(result.work_dir, work_dir.display().to_string());
    assert_eq!(result.template_source, "default template");

    // verify files including Dockerfile and .gitignore
    verify_template_files(&work_dir);
}

#[test]
fn test_force_rewrite() {
    let temp_dir = TempDir::new().unwrap();
    let work_dir = temp_dir.path().join("force_rewrite_test");

    // initial copy
    IOProvider::initiate_project_impl(&work_dir, false).unwrap();

    // read original .gitignore content
    let gitignore_path = work_dir.join(".gitignore");
    let original_gitignore = fs::read_to_string(&gitignore_path).unwrap();

    // mess with files: add extra file and modify .gitignore
    fs::write(work_dir.join("extra_file.txt"), "should be deleted").unwrap();
    fs::write(&gitignore_path, "modified content").unwrap();
    assert!(work_dir.join("extra_file.txt").exists());

    // force rewrite
    let result = IOProvider::initiate_project_impl(&work_dir, true).unwrap();

    // verify result
    assert!(result.files_copied > 0);

    // verify extra file was removed
    assert!(
        !work_dir.join("extra_file.txt").exists(),
        "extra_file.txt should be removed by force_rewrite"
    );

    // verify .gitignore is restored to original
    let restored_gitignore = fs::read_to_string(&gitignore_path).unwrap();
    assert_eq!(
        original_gitignore, restored_gitignore,
        ".gitignore should be restored to original content"
    );

    verify_template_files(&work_dir);
}

#[test]
fn test_pessimistic_no_write_access() {
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

    let result = IOProvider::initiate_project_impl(&work_dir, false);

    // should fail with permission error
    assert!(result.is_err(), "should fail due to permission denied");

    // cleanup: restore permissions before dropping TempDir
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&work_dir).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&work_dir, perms).unwrap();
    }
}
