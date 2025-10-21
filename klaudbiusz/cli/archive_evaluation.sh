#!/bin/bash
# Archive all evaluated apps with their evaluation reports

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Create archive name with timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
ARCHIVE_DIR="${PROJECT_ROOT}/archive/${TIMESTAMP}"
ARCHIVE_NAME="klaudbiusz_evaluation_${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="${PROJECT_ROOT}/${ARCHIVE_NAME}"

echo "📦 Creating evaluation archive..."
echo "Timestamp: ${TIMESTAMP}"
echo "Archive Dir: archive/${TIMESTAMP}/"
echo "Archive File: ${ARCHIVE_NAME}"
echo ""

# Change to project root
cd "${PROJECT_ROOT}"

# Create archive directory structure
echo "📁 Syncing to archive/${TIMESTAMP}/..."
mkdir -p "${ARCHIVE_DIR}"

# Sync app directory to archive (exclude large build artifacts)
if [ -d "app" ]; then
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
    echo "   ✅ Synced app/ directory"
fi

# Sync app-eval directory to archive (contains all evaluation reports)
if [ -d "app-eval" ]; then
    rsync -a app-eval/ "${ARCHIVE_DIR}/app-eval/"
    echo "   ✅ Synced app-eval/ directory (evaluation reports)"
fi

echo ""
echo "📦 Creating compressed archive..."

# Create tar.gz archive with all apps and reports
tar -czf "${ARCHIVE_NAME}" \
  --exclude='app/*/node_modules' \
  --exclude='app/*/client/node_modules' \
  --exclude='app/*/server/node_modules' \
  --exclude='app/*/client/dist' \
  --exclude='app/*/server/dist' \
  --exclude='app/*/.next' \
  --exclude='app/*/build' \
  -C "${ARCHIVE_DIR}" \
  .

# Get sizes
ARCHIVE_SIZE=$(du -h "${ARCHIVE_NAME}" | cut -f1)
ARCHIVE_DIR_SIZE=$(du -sh "${ARCHIVE_DIR}" | cut -f1)

echo "✅ Archive created successfully!"
echo ""
echo "Archive Details:"
echo "  Persistent: archive/${TIMESTAMP}/ (${ARCHIVE_DIR_SIZE})"
echo "  Compressed: ${ARCHIVE_NAME} (${ARCHIVE_SIZE})"
echo ""

# Show contents summary
echo "Archive Contents:"
tar -tzf "${ARCHIVE_NAME}" | head -20
TOTAL_FILES=$(tar -tzf "${ARCHIVE_NAME}" | wc -l | tr -d ' ')
echo "  ... (${TOTAL_FILES} total files)"
echo ""

# Create checksum
CHECKSUM=$(shasum -a 256 "${ARCHIVE_NAME}" | cut -d' ' -f1)
echo "SHA-256: ${CHECKSUM}" | tee "${ARCHIVE_NAME}.sha256"

# Move both tar.gz and checksum into the archive directory
mv "${ARCHIVE_NAME}" "${ARCHIVE_DIR}/"
mv "${ARCHIVE_NAME}.sha256" "${ARCHIVE_DIR}/"

echo ""
echo "🎉 Archive complete!"
echo ""
echo "Locations:"
echo "  📁 archive/${TIMESTAMP}/  (persistent, contains all files)"
echo "  📦 archive/${TIMESTAMP}/${ARCHIVE_NAME}  (compressed backup)"
echo "  🔐 archive/${TIMESTAMP}/${ARCHIVE_NAME}.sha256  (checksum)"
