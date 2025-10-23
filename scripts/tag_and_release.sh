#!/bin/bash
set -e

# usage: ./tag_and_release.sh v0.1.0 <commit_sha> "Release notes here"

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <version_tag> <commit_sha> [release_notes]"
    echo "Example: $0 v0.1.0 abc1234 \"Initial release\""
    exit 1
fi

VERSION=$1
COMMIT=$2
NOTES=${3:-"Release $VERSION"}

# validate tag format
if [[ ! $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Version must follow format v0.0.0"
    exit 1
fi

# check if commit exists
if ! git rev-parse "$COMMIT" >/dev/null 2>&1; then
    echo "Error: Commit $COMMIT not found"
    exit 1
fi

# check if tag already exists
if git rev-parse "$VERSION" >/dev/null 2>&1; then
    echo "Error: Tag $VERSION already exists"
    exit 1
fi

# find the CI run for this commit
echo "Finding CI run for commit $COMMIT..."
RUN_ID=$(gh run list --commit "$COMMIT" --workflow="Rust" --status=success --json databaseId --jq '.[0].databaseId')

if [ -z "$RUN_ID" ]; then
    echo "Error: No successful CI run found for commit $COMMIT"
    echo "Make sure the commit has been pushed and CI completed successfully"
    exit 1
fi

echo "Found CI run: $RUN_ID"

# create temporary directory for artifacts
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

echo "Downloading artifacts from CI..."
cd "$TEMP_DIR"

gh run download "$RUN_ID" --name dabgent-mcp-linux-x86_64
gh run download "$RUN_ID" --name dabgent-mcp-macos-arm64

# verify artifacts exist
if [ ! -f "dabgent_mcp" ]; then
    echo "Error: Artifacts not found in CI run"
    ls -la
    exit 1
fi

# rename artifacts for clarity
mv dabgent_mcp dabgent_mcp-linux-x86_64 || true
cd - >/dev/null

cd "$TEMP_DIR"
if [ -f "dabgent_mcp" ]; then
    mv dabgent_mcp dabgent_mcp-macos-arm64
fi
cd - >/dev/null

echo "Creating tag $VERSION at commit $COMMIT..."
git tag -a "$VERSION" "$COMMIT" -m "$NOTES"

echo "Pushing tag..."
git push origin "$VERSION"

echo "Creating GitHub release..."
gh release create "$VERSION" \
    --title "$VERSION" \
    --notes "$NOTES" \
    "$TEMP_DIR"/*

echo ""
echo "Release created successfully!"
echo "View at: https://github.com/appdotbuild/agent/releases/tag/$VERSION"
