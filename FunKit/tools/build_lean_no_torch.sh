#!/usr/bin/env bash
set -euo pipefail

APP_NAME="funkit"                     # whatever your .spec builds (dist/<APP_NAME>)
SPEC_FILE="funkit.spec"               # change if your spec has a different name
STAMP="$(date -u +'%Y%m%d_%H%M%S')"
VER="$(cat VERSION 2>/dev/null || echo 'dev')"

echo "==> Archiving current dist (if present)…"
if [[ -d "dist/${APP_NAME}" ]]; then
  mkdir -p release-archives
  ARCHIVE="release-archives/${APP_NAME}-linux-${VER}-${STAMP}.tgz"
  (cd dist && tar -czf "../${ARCHIVE}" "${APP_NAME}")
  sha256sum "${ARCHIVE}" | tee "${ARCHIVE}.sha256"
  du -h "${ARCHIVE}"
else
  echo "No existing dist/${APP_NAME} to archive (skipping)."
fi

echo "==> Cleaning previous build artifacts…"
rm -rf build dist

echo "==> Rebuilding WITHOUT PyTorch (and friends)…"
# If you prefer CLI only, uncomment this line (works even without editing the .spec):
# pyinstaller -y --clean --name "${APP_NAME}" \
#   --exclude-module torch --exclude-module torchvision --exclude-module torchaudio \
#   --exclude-module tensorflow --exclude-module cv2 \
#   main.py

# Default: build from your spec (after you add the excludes shown below)
pyinstaller -y --clean "${SPEC_FILE}"

echo "==> Size of new build:"
du -sh "dist/${APP_NAME}" || true

echo "==> Build complete. Artifacts in dist/${APP_NAME}"

