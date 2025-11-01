use eyre::Result;
use serde::Deserialize;

const GITHUB_API_URL: &str = "https://api.github.com/repos/appdotbuild/agent/releases/latest";

#[derive(Debug, Deserialize)]
struct GitHubRelease {
    tag_name: String,
}

async fn fetch_latest_version() -> Result<String> {
    let client = reqwest::Client::builder()
        .user_agent("edda-mcp")
        .timeout(std::time::Duration::from_secs(5))
        .build()?;

    let response: GitHubRelease = client.get(GITHUB_API_URL).send().await?.json().await?;

    // strip 'v' prefix if present
    let version = response
        .tag_name
        .strip_prefix('v')
        .unwrap_or(&response.tag_name)
        .to_string();

    Ok(version)
}

fn compare_versions(current: &str, latest: &str) -> Result<std::cmp::Ordering> {
    let current_ver = semver::Version::parse(current)?;
    let latest_ver = semver::Version::parse(latest)?;
    Ok(current_ver.cmp(&latest_ver))
}

pub async fn check_for_updates() -> Result<()> {
    let latest = fetch_latest_version().await?;
    let current = env!("CARGO_PKG_VERSION");

    // compare and notify
    match compare_versions(current, &latest)? {
        std::cmp::Ordering::Less => {
            eprintln!(
                "\n📦 Update available: v{} → v{}\n   Run: curl -LsSf https://raw.githubusercontent.com/appdotbuild/agent/refs/heads/main/edda/install.sh | sh\n",
                current, latest
            );
        }
        _ => {} // up to date or ahead (dev version)
    }

    Ok(())
}
