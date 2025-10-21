#!/bin/bash
# Clean up evaluated apps and reports after archiving
# CAUTION: This will delete all generated apps and evaluation reports!

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root
cd "${PROJECT_ROOT}"

# Count apps before deletion
APP_COUNT=$(find app -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')

echo "⚠️  CLEANUP WARNING"
echo "This will delete:"
echo "  - All apps in app/ directory (${APP_COUNT} apps)"
echo "  - All evaluation reports (JSON, CSV, MD)"
echo ""
echo "📁 Content will be synced to archive/ first"
echo ""
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "❌ Cleanup cancelled"
    exit 0
fi

echo ""
echo "📁 Syncing to archive before cleanup..."
echo ""

# Create archive name with timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
ARCHIVE_DIR="${PROJECT_ROOT}/archive/${TIMESTAMP}"

# Create archive directory structure
mkdir -p "${ARCHIVE_DIR}"

# Sync app directory to archive (exclude large build artifacts)
if [ -d "app" ] && [ "$APP_COUNT" -gt 0 ]; then
    rsync -a --exclude='node_modules' \
             --exclude='client/node_modules' \
             --exclude='server/node_modules' \
             --exclude='client/dist' \
             --exclude='server/dist' \
             --exclude='.next' \
             --exclude='build' \
             --exclude='*.tar.gz' \
             --exclude='*.tar.gz.sha256' \
             app/ "${ARCHIVE_DIR}/app/"
    echo "   ✅ Synced app/ → archive/${TIMESTAMP}/app/"
fi

# Sync app-eval directory to archive (contains all evaluation reports)
if [ -d "app-eval" ]; then
    rsync -a app-eval/ "${ARCHIVE_DIR}/app-eval/"
    echo "   ✅ Synced app-eval/ → archive/${TIMESTAMP}/app-eval/"
fi

echo ""
echo "🧹 Starting cleanup..."
echo ""

# Remove all generated apps
if [ -d "app" ] && [ "$APP_COUNT" -gt 0 ]; then
    echo "📂 Removing ${APP_COUNT} apps from app/ directory..."
    rm -rf app/*/
    echo "   ✅ Removed all apps from app/"
else
    echo "   ℹ️  No apps to remove"
fi

# Remove app-eval directory (all evaluation reports)
echo ""
echo "📄 Removing evaluation reports..."

if [ -d "app-eval" ]; then
    rm -rf app-eval/
    echo "   ✅ Removed app-eval/ directory (all evaluation reports)"
fi

# Remove old tar.gz archives from app/ (they belong in archive/)
if ls app/*.tar.gz 1> /dev/null 2>&1; then
    rm -f app/*.tar.gz app/*.tar.gz.sha256
    echo "   ✅ Removed old archives from app/"
fi

# Summary
echo ""
echo "✅ Cleanup complete!"
echo ""
echo "📁 Kept (safe in archive/):"
echo "  - archive/${TIMESTAMP}/app/ (all app code)"
echo "  - archive/${TIMESTAMP}/app-eval/ (all evaluation reports)"
echo "  - archive/*/ (all previous evaluations)"
echo ""
echo "📦 Also kept:"
echo "  - archive/*/klaudbiusz_evaluation_*.tar.gz (compressed backups)"
echo "  - eval-docs/ (evaluation framework)"
echo "  - cli/ (scripts)"
echo ""
echo "🗑️  Removed:"
echo "  - app/*/ (${APP_COUNT} generated apps)"
echo "  - app-eval/ (evaluation reports)"
echo ""
echo "✨ Ready for fresh generation run!"
