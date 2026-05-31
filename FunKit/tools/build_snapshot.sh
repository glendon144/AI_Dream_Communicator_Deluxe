#!/usr/bin/env bash
set -Eeuo pipefail

# =============================================================================
# FunKit Snapshot Build Script — Safe, non-recursive version
#
# What changed vs your previous script?
# - Uses a temporary build directory outside the project tree (mktemp -d)
#   so we never copy a directory into itself and cause infinite nesting.
# - Explicit rsync excludes for common build/venv folders.
# - Creates a venv in the temp area and builds there.
# - Cleans up the temp area on exit.
# =============================================================================

echo "📦 Starting FunKit Snapshot Build (safe mode)..."

# Snapshot destination (kept the same default)
SNAPSHOT_DIR="${SNAPSHOT_DIR:-$HOME/funkit-snapshots}"

# Record the project root (where this script is run from)
PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"

# Create a temp build dir OUTSIDE the project tree to avoid recursion
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/funkit_snapshot_build.XXXXXX")"

# Ensure cleanup even on failure
cleanup() {
  if [[ -n "${BUILD_DIR:-}" && -d "$BUILD_DIR" ]]; then
    rm -rf "$BUILD_DIR"
  fi
}
trap cleanup EXIT

# Create snapshots directory
mkdir -p "$SNAPSHOT_DIR"

# Timestamped build name
SNAPSHOT_NAME="${SNAPSHOT_NAME:-funkit-$(date +%Y%m%d-%H%M%S)}"

echo "📁 Project root : $PROJECT_ROOT"
echo "🧪 Build dir    : $BUILD_DIR"
echo "🗂  Snapshots    : $SNAPSHOT_DIR"
echo "🏷  Artifact     : $SNAPSHOT_NAME"

# -----------------------------------------------------------------------------
# Step 1: Copy source into isolated workspace
# -----------------------------------------------------------------------------
mkdir -p "$BUILD_DIR/src"
echo "🛰  Syncing source into temp workspace..."

# Exclude common noise and anything that could cause recursion
rsync -a \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='.mypy_cache' \
  --exclude='.pytest_cache' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='dist' \
  --exclude='build' \
  --exclude='*.spec' \
  "$PROJECT_ROOT"/ "$BUILD_DIR/src/"

# -----------------------------------------------------------------------------
# Step 2: Build in an isolated virtual environment
# -----------------------------------------------------------------------------
cd "$BUILD_DIR/src"

echo "🐍 Creating virtualenv..."
python3 -m venv "$BUILD_DIR/venv"
# shellcheck disable=SC1091
source "$BUILD_DIR/venv/bin/activate"

echo "📚 Installing dependencies..."
python -m pip install --upgrade pip wheel
if [[ -f requirements.txt ]]; then
  python -m pip install -r requirements.txt
fi
python -m pip install pyinstaller

# -----------------------------------------------------------------------------
# Step 3: Build single-file executable
# -----------------------------------------------------------------------------
echo "📄 Building standalone FunKit binary..."
# If you want to embed the storage folder at runtime, add:
#   --add-data "storage:storage"
pyinstaller main.py --onefile --clean --name "$SNAPSHOT_NAME"

# -----------------------------------------------------------------------------
# Step 4: Move artifact to snapshots dir
# -----------------------------------------------------------------------------
echo "📦 Moving final binary to $SNAPSHOT_DIR/"
mv "dist/$SNAPSHOT_NAME" "$SNAPSHOT_DIR/$SNAPSHOT_NAME.bin"

echo "✅ Snapshot complete: $SNAPSHOT_DIR/$SNAPSHOT_NAME.bin"
