#!/bin/sh
# shellcheck shell=dash
# shellcheck disable=SC2039  # local is non-POSIX
#
# Installer for edda MCP server
# Downloads and installs the latest release from GitHub

set -u

APP_NAME="edda_mcp"
GITHUB_REPO="appdotbuild/agent"
GITHUB_BASE_URL="https://github.com/${GITHUB_REPO}"

# Version handling - support EDDA_VERSION env var
VERSION="${EDDA_VERSION:-latest}"
if [ "$VERSION" != "latest" ]; then
    # Prepend 'v' if not present
    case "$VERSION" in
        v*) ;;
        *) VERSION="v${VERSION}" ;;
    esac
fi

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
edda MCP server installer

Downloads and installs the latest edda MCP server binary from:
${GITHUB_BASE_URL}/releases/latest

The binary will be installed to:
    \$HOME/.local/bin/edda_mcp

USAGE:
    install.sh [OPTIONS]

OPTIONS:
    -h, --help
            Print this help message

ENVIRONMENT VARIABLES:
    EDDA_VERSION
            Specify version to install (default: latest)
            Examples:
                EDDA_VERSION="0.0.7" ./install.sh
                EDDA_VERSION="v0.0.7" ./install.sh

SUPPORTED PLATFORMS:
    - macOS (Apple Silicon / ARM64)
    - Linux (x86_64)
EOF
}

# Color and formatting
BOLD=$(tput bold 2>/dev/null || echo '')
RESET=$(tput sgr0 2>/dev/null || echo '')
RED=$(tput setaf 1 2>/dev/null || echo '')
GREEN=$(tput setaf 2 2>/dev/null || echo '')
YELLOW=$(tput setaf 3 2>/dev/null || echo '')
BLUE=$(tput setaf 4 2>/dev/null || echo '')
CYAN=$(tput setaf 6 2>/dev/null || echo '')
DIM=$(tput dim 2>/dev/null || echo '')

say() {
    echo "$1"
}

info() {
    echo "${CYAN}▸${RESET} $1"
}

success() {
    echo "${GREEN}✓${RESET} $1"
}

warn() {
    echo "${YELLOW}⚠${RESET} $1"
}

err() {
    echo "${RED}✗ ERROR${RESET}: $1" >&2
    exit 1
}

header() {
    echo ""
    echo "${BOLD}$1${RESET}"
    echo ""
}

# Simple spinner for long operations
spinner() {
    local pid=$1
    local message=$2
    local spinstr='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local delay=0.1

    printf "${CYAN}▸${RESET} %s " "$message"

    while kill -0 "$pid" 2>/dev/null; do
        local temp=${spinstr#?}
        printf "[%c]" "$spinstr"
        spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b"
    done

    printf "   \b\b\b"
    wait "$pid"
    return $?
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

# Download using curl or wget with progress
downloader() {
    local _url="$1"
    local _file="$2"

    if check_cmd curl; then
        info "Downloading..."
        curl -fL --progress-bar "$_url" -o "$_file" 2>&1
        if [ ! -f "$_file" ]; then
            return 1
        fi
    elif check_cmd wget; then
        info "Downloading..."
        wget --quiet --show-progress "$_url" -O "$_file"
        if [ ! -f "$_file" ]; then
            return 1
        fi
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

    # Print banner
    echo ""
    echo "${BOLD}${CYAN}edda MCP Server${RESET}"
    echo ""

    # Detect architecture
    local _arch
    _arch="$(get_architecture)"

    # Construct download URL
    local _binary_name="${APP_NAME}-${_arch}"
    local _download_url
    if [ "$VERSION" = "latest" ]; then
        _download_url="${GITHUB_BASE_URL}/releases/latest/download/${_binary_name}"
    else
        _download_url="${GITHUB_BASE_URL}/releases/download/${VERSION}/${_binary_name}"
    fi

    # Create temporary directory
    local _tmpdir
    _tmpdir="$(ensure mktemp -d)" || return 1
    local _tmpfile="$_tmpdir/$APP_NAME"

    # Download
    info "Version: ${BOLD}$VERSION${RESET}"
    info "Platform: ${BOLD}$_arch${RESET}"
    echo "  ${DIM}$_download_url${RESET}"
    echo ""

    if ! downloader "$_download_url" "$_tmpfile"; then
        err "Failed to download"
    fi

    # Determine installation directory
    local _install_dir="${INFERRED_HOME}/.local/bin"
    local _install_path="${_install_dir}/${APP_NAME}"

    ensure mkdir -p "$_install_dir"
    ensure mv "$_tmpfile" "$_install_path"
    ensure chmod +x "$_install_path"

    # Clean up
    ensure rm -rf "$_tmpdir"

    echo ""
    success "Installed to ${BOLD}$_install_path${RESET}"

    # Check if install dir is on PATH
    case ":${PATH}:" in
        *:"$_install_dir":*)
            ;;
        *)
            echo ""
            warn "Add to PATH: ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
            ;;
    esac

    # Run environment check (non-blocking but shows status)
    echo ""
    echo "${BOLD}Running environment check...${RESET}"
    echo ""
    if "$_install_path" check; then
        echo ""
        success "Environment validation passed"
    else
        echo ""
        warn "Environment needs configuration - see checks above"
    fi

    # Inform about .env.example creation
    echo ""
    echo "${BOLD}Environment Configuration${RESET}"
    echo ""
    echo "  A template .env.example has been created at:"
    echo "  ${CYAN}~/.edda/.env.example${RESET}"
    echo ""
    echo "  To configure credentials:"
    echo "  1. ${DIM}cp ~/.edda/.env.example ~/.edda/.env${RESET}"
    echo "  2. Edit ${DIM}~/.edda/.env${RESET} and add your credentials"
    echo "  3. Run ${DIM}edda_mcp check${RESET} to validate"
    echo ""
    echo "  Found a bug? Please report via: ${DIM}edda_mcp yell${RESET}"
    echo ""

    print_claude_instructions "$_install_path"
}

print_claude_instructions() {
    local _install_path="$1"
    local _ostype
    _ostype="$(uname -s)"

    # Determine Claude Desktop config path based on OS
    local _claude_desktop_config
    case "$_ostype" in
        Darwin)
            _claude_desktop_config="~/Library/Application Support/Claude/claude_desktop_config.json"
            ;;
        Linux)
            _claude_desktop_config="~/.config/Claude/claude_desktop_config.json"
            ;;
        *)
            _claude_desktop_config="<see Claude Desktop documentation for your OS>"
            ;;
    esac

    echo ""
    echo "${BOLD}Next steps:${RESET}"
    echo ""

    # Claude Code section
    echo "${BOLD}For Claude Code:${RESET}"
    echo ""
    echo "  ${CYAN}claude mcp add --transport stdio edda -- $_install_path${RESET}"
    echo ""
    echo ""

    # Cursor section
    echo "${BOLD}For Cursor:${RESET}"
    echo ""
    echo "  Add this to ${DIM}~/.cursor/mcp.json${RESET}"
    echo ""
    cat <<EOF
  ${CYAN}{
    "mcpServers": {
      "edda": {
        "command": "$_install_path",
        "args": []
      }
    }
  }${RESET}
EOF
    echo ""
    echo "  Then restart Cursor"
    echo ""
}

download_and_install "$@" || exit 1
