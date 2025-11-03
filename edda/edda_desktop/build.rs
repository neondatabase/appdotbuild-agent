use anyhow::{Context, Result};
use std::path::PathBuf;
use std::process::Command;

fn main() -> Result<()> {
    println!("cargo:rerun-if-changed=../edda_mcp/src");
    println!("cargo:rerun-if-changed=../edda_mcp/Cargo.toml");

    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR")?);
    let profile = std::env::var("PROFILE")?;

    // workspace root is parent of edda_desktop
    let workspace_root = manifest_dir
        .parent()
        .context("Failed to get workspace root")?;

    let src_binary = workspace_root
        .join("target")
        .join(&profile)
        .join("edda_mcp");

    // only build if binary doesn't exist
    if !src_binary.exists() {
        let build_profile = if profile == "release" { "--release" } else { "" };

        println!("cargo:warning=Building edda_mcp (not found in target/{})...", profile);
        let status = Command::new("cargo")
            .args(["build", build_profile, "--package", "edda_mcp"].iter().filter(|s| !s.is_empty()))
            .current_dir(workspace_root)
            .status()
            .context("Failed to build edda_mcp")?;

        if !status.success() {
            anyhow::bail!("Failed to build edda_mcp");
        }
    }

    if !src_binary.exists() {
        anyhow::bail!("edda_mcp binary not found at {:?}", src_binary);
    }

    // copy to OUT_DIR for embedding
    let out_dir = PathBuf::from(std::env::var("OUT_DIR")?);
    let dest_binary = out_dir.join("edda_mcp");

    std::fs::copy(&src_binary, &dest_binary)
        .context("Failed to copy edda_mcp to OUT_DIR")?;

    println!("cargo:warning=Embedded edda_mcp from: {:?}", src_binary);

    Ok(())
}
