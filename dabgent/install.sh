#!/bin/sh
# shellcheck shell=dash
# shellcheck disable=SC2039  # local is non-POSIX
#
# Installer for dabgent MCP server
# Downloads and installs the latest release from GitHub

set -u

APP_NAME="dabgent_mcp"
GITHUB_REPO="appdotbuild/agent"
GITHUB_BASE_URL="https://github.com/${GITHUB_REPO}"

# Determine HOME directory, handling edge cases
get_home() {
    if [ -n "${HOME:-}" ]; then
        echo "$HOME"
    elif [ -n "${USER:-}" ]; then
        getent passwd "$USER" | cut -d: -f6
    else
        getent passwd "$(id -un)" | cut -d: -f6
    fi
}

INFERRED_HOME=$(get_home)

usage() {
    cat <<EOF
dabgent MCP server installer

Downloads and installs the latest dabgent MCP server binary from:
${GITHUB_BASE_URL}/releases/latest

The binary will be installed to:
    \$HOME/.local/bin/dabgent_mcp

USAGE:
    install.sh [OPTIONS]

OPTIONS:
    -h, --help
            Print this help message

SUPPORTED PLATFORMS:
    - macOS (Apple Silicon / ARM64)
    - Linux (x86_64)
EOF
}

say() {
    echo "$1"
}

err() {
    local red
    local reset
    red=$(tput setaf 1 2>/dev/null || echo '')
    reset=$(tput sgr0 2>/dev/null || echo '')
    say "${red}ERROR${reset}: $1" >&2
    exit 1
}

need_cmd() {
    if ! check_cmd "$1"; then
        err "need '$1' (command not found)"
    fi
}

check_cmd() {
    command -v "$1" > /dev/null 2>&1
    return $?
}

ensure() {
    if ! "$@"; then
        err "command failed: $*"
    fi
}

# Download using curl or wget
downloader() {
    local _url="$1"
    local _file="$2"

    if check_cmd curl; then
        ensure curl -sSfL "$_url" -o "$_file"
    elif check_cmd wget; then
        ensure wget "$_url" -O "$_file"
    else
        err "need 'curl' or 'wget' to download files"
    fi
}

get_architecture() {
    local _ostype
    local _cputype
    _ostype="$(uname -s)"
    _cputype="$(uname -m)"

    case "$_ostype" in
        Darwin)
            # Handle macOS, checking for Apple Silicon
            if [ "$_cputype" = "arm64" ] || [ "$_cputype" = "aarch64" ]; then
                echo "macos-arm64"
                return 0
            else
                err "Only macOS on Apple Silicon (ARM64) is supported. Found: $_cputype"
            fi
            ;;
        Linux)
            if [ "$_cputype" = "x86_64" ] || [ "$_cputype" = "amd64" ]; then
                echo "linux-x86_64"
                return 0
            else
                err "Only Linux x86_64 is supported. Found: $_cputype"
            fi
            ;;
        *)
            err "Unsupported operating system: $_ostype"
            ;;
    esac
}

download_and_install() {
    need_cmd uname
    need_cmd mktemp
    need_cmd chmod
    need_cmd mkdir
    need_cmd rm

    # Parse command line arguments
    for arg in "$@"; do
        case "$arg" in
            --help|-h)
                usage
                exit 0
                ;;
            *)
                err "unknown option: $arg"
                ;;
        esac
    done

    # Detect architecture
    local _arch
    _arch="$(get_architecture)"
    say "Detected platform: $_arch"

    # Construct download URL
    local _binary_name="${APP_NAME}-${_arch}"
    local _download_url="${GITHUB_BASE_URL}/releases/latest/download/${_binary_name}"

    # Create temporary directory
    local _tmpdir
    _tmpdir="$(ensure mktemp -d)" || return 1
    local _tmpfile="$_tmpdir/$APP_NAME"

    say "Downloading ${APP_NAME}..."
    say "  from: $_download_url"

    if ! downloader "$_download_url" "$_tmpfile"; then
        say "Failed to download from $_download_url"
        say "This may indicate a network error or that no release exists for your platform."
        exit 1
    fi

    # Determine installation directory
    local _install_dir="${INFERRED_HOME}/.local/bin"
    local _install_path="${_install_dir}/${APP_NAME}"

    say "Installing to $_install_dir..."
    ensure mkdir -p "$_install_dir"
    ensure mv "$_tmpfile" "$_install_path"
    ensure chmod +x "$_install_path"

    # Clean up
    ensure rm -rf "$_tmpdir"

    say ""
    say "Installation complete!"
    say ""
    say "Binary installed at: $_install_path"

    # Check if install dir is on PATH
    case ":${PATH}:" in
        *:"$_install_dir":*)
            say "$_install_dir is already on your PATH"
            ;;
        *)
            say ""
            say "NOTE: $_install_dir is not on your PATH."
            say "Add it by running:"
            say ""
            say "    export PATH=\"\$HOME/.local/bin:\$PATH\""
            say ""
            say "Add this line to your shell profile (~/.bashrc, ~/.zshrc, etc.) to make it permanent."
            ;;
    esac

    print_claude_instructions "$_install_path"
}

print_claude_instructions() {
    local _install_path="$1"

    say ""
    say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    say "To use dabgent with Claude Code:"
    say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    say ""
    say "Run the following command to add the MCP server:"
    say ""
    say "    claude mcp add --transport stdio dabgent -- $_install_path"
    say ""
    say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    say ""
    say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    say "To use dabgent with Claude Desktop:"
    say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    say ""
    say "Add the following to your Claude Desktop configuration:"
    say ""
    say "macOS: ~/Library/Application Support/Claude/claude_desktop_config.json"
    say "Linux: ~/.config/Claude/claude_desktop_config.json"
    say ""
    say "Configuration:"
    say ""
    cat <<EOF
{
  "mcpServers": {
    "dabgent": {
      "command": "$_install_path",
      "args": []
    }
  }
}
EOF
    say ""
    say "If you already have other MCP servers configured, add the"
    say "\"dabgent\" entry to your existing \"mcpServers\" object."
    say ""
    say "After updating the config, restart Claude Desktop."
    say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

download_and_install "$@" || exit 1
