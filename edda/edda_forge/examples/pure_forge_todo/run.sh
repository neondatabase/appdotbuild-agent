#!/bin/bash
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
RUN_DIR="${RUN_DIR:-$(mktemp -d "/tmp/edda-forge-pure-todo.XXXXXX")}"

mkdir -p "$RUN_DIR/seed"

if ! command -v claude >/dev/null 2>&1; then
  echo "error: claude CLI is required for this example." >&2
  exit 1
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "warning: ANTHROPIC_API_KEY is not set." >&2
  echo "The run may still work if Claude Code is already authenticated locally." >&2
fi

if [ ! -d "${HOME:-}/.claude" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "error: Claude auth not detected." >&2
  echo "Set ANTHROPIC_API_KEY or authenticate with Claude Code first." >&2
  exit 1
fi

echo "Running pure forge example in: $RUN_DIR"

edda-forge \
  --runtime local \
  --config "$SCRIPT_DIR/forge-base.toml" \
  --source "$RUN_DIR/seed" \
  --prompt "Create a simple Streamlit todo app with add, complete, and delete functionality." \
  --output "$RUN_DIR/todo-base" \
  --export-dir

edda-forge \
  --runtime local \
  --config "$SCRIPT_DIR/forge-clown.toml" \
  --source "$RUN_DIR/todo-base" \
  --prompt "Make the todo app look clowny with circus colors, rainbow heading, and playful labels while preserving behavior." \
  --output "$RUN_DIR/todo-clown"

cp -R "$RUN_DIR/todo-base" "$RUN_DIR/todo-base-patched"
(
  cd "$RUN_DIR/todo-base-patched"
  rm -rf .venv
  git apply "$RUN_DIR/todo-clown.patch"
  python3 -m py_compile app.py
  ruff check .
)

echo ""
echo "Artifacts:"
echo "  Base app:      $RUN_DIR/todo-base"
echo "  Clown patch:   $RUN_DIR/todo-clown.patch"
echo "  Patched check: $RUN_DIR/todo-base-patched (syntax verified)"
