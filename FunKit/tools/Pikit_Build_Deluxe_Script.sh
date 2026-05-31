#!/bin/bash
# =============================================================================
# FunKit Snapshot Build Script — Heavily Commented Edition
#
# Document summary
# - Purpose:
#   Creates a timestamped, self-contained snapshot build (PyInstaller one-file)
#   of the FunKit project and deposits the binary in $HOME/funkit-snapshots.
#
# - What it does (high level):
#   1) Prepares a clean build workspace.
#   2) Copies the project source into that workspace (excluding .git and __pycache__).
#   3) Copies the current storage directory into the workspace.
#   4) Creates a virtual environment and installs dependencies.
#   5) Uses PyInstaller to produce a standalone binary from main.py.
#   6) Moves the resulting binary to a snapshots directory with a timestamped name.
#
# - Primary outputs:
#   $HOME/funkit-snapshots/funkit_snapshot_YYYY-MM-DD_HH-MM-SS.bin
#
# - Use cases:
#   • Shareable snapshot for non-developers or testers without requiring Python installed.
#   • Reproducible test builds for QA to capture a point-in-time state of the app.
#   • CI/CD artifact generation for nightly or on-demand builds.
#   • Demo or field distribution that can run on compatible target systems.
#   • Quick backup of a working build, aligned with current requirements.txt.
#
# - Requirements on the system:
#   • bash, rsync, python3 with venv module, pip, and internet connectivity (to install dependencies).
#   • PyInstaller (installed by this script into the virtualenv).
#   • A main.py entry point in the project root.
#
# - Notes and caveats:
#   • This script uses `set -e` to stop immediately on the first error.
#   • PyInstaller --onefile does NOT automatically include arbitrary folders.
#     As written, copying "storage" into the build directory makes it available DURING build,
#     but it is NOT embedded into the final one-file binary unless explicitly added via --add-data
#     or a .spec file.
#     If you need "storage" embedded in the binary, consider:
#       pyinstaller main.py --onefile --clean --name "$SNAPSHOT_NAME" \
#         --add-data "storage:storage"
#     Alternatively, use a one-folder build or ship the "storage" directory alongside the binary.
#   • The output is renamed with a .bin extension for clarity; on Linux/macOS this is not required.
#     On Windows, you'd want .exe instead and to build on Windows.
#   • The script places the build directory (funkit_snapshot_build) inside the project root.
#     rsync builds its file list before copying, so it typically avoids recursing into the target.
#     Still, excluding the build dir explicitly is a common safety measure if you modify this script.
#   • If the "storage" directory does not exist, the copy step will fail and the script will exit.
#
# - Portability:
#   Targeted at Unix-like systems (Linux/macOS). For Windows, use PowerShell/CMD and
#   a Windows Python environment to produce a native .exe.
#
# =============================================================================

# Exit immediately if any command returns a non-zero status.
# This prevents continuing after a failure (e.g., pip install error).
set -e

# Log: starting the snapshot build process (includes emojis for readability).
echo "📦 Starting FunKit Snapshot Build..."

# -----------------------------------------------------------------------------
# Step 1: Define snapshot naming and directories, and prepare a clean workspace.
# -----------------------------------------------------------------------------

# SNAPSHOT_NAME is timestamped to make every run produce a unique build artifact.
SNAPSHOT_NAME="funkit_snapshot_$(date +%Y-%m-%d_%H-%M-%S)"

# SNAPSHOT_DIR is where the final binary will be moved for safekeeping.
SNAPSHOT_DIR="$HOME/funkit-snapshots"

# BUILD_DIR is the temporary build workspace created inside the project root.
# Note: Keeping BUILD_DIR within the project root is convenient, but be mindful
# of rsync behavior. It’s generally fine because rsync compiles the file list first,
# but consider excluding BUILD_DIR explicitly if you customize this script.
BUILD_DIR="funkit_snapshot_build"

# Ensure the snapshots directory exists.
mkdir -p "$SNAPSHOT_DIR"

# Start fresh by removing any old build workspace, then recreate it.
rm -rf "$BUILD_DIR"
mkdir "$BUILD_DIR"

# Copy project source into the build workspace.
# -a: archive mode (preserves permissions, timestamps, symlinks)
# -v: verbose output
# --exclude='__pycache__': omit Python bytecode caches
# --exclude='.git': omit Git metadata
# Dot (.) means "copy the current directory contents".
# Destination is the BUILD_DIR we just created.
echo "🔁 Copying project source into $BUILD_DIR..."
rsync -av --exclude='__pycache__' --exclude='.git' . "$BUILD_DIR/"

# Copy the current 'storage' folder into the build workspace as well.
# NOTE: This makes 'storage' available during build and for one-folder builds,
# but it will NOT be embedded in a PyInstaller --onefile binary unless you
# add it via --add-data or a .spec file. See the summary notes above.
# If 'storage' doesn't exist, this command will fail and the script will exit.
echo "🗂️ Copying current storage folder into snapshot build..."
cp -r storage "$BUILD_DIR/"

# -----------------------------------------------------------------------------
# Step 2: Enter the build directory and prepare an isolated Python environment.
# -----------------------------------------------------------------------------

# Move into the build workspace so all subsequent actions operate from there.
cd "$BUILD_DIR"

# Create a dedicated virtual environment to ensure a clean, reproducible build.
echo "🐍 Creating virtualenv for isolated build..."
python3 -m venv snapshot-env

# Activate the virtual environment so pip installs into it, not system-wide.
source snapshot-env/bin/activate

# Install dependencies into the virtual environment.
echo "📚 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

# -----------------------------------------------------------------------------
# Step 3: Build the standalone binary with PyInstaller.
# -----------------------------------------------------------------------------

# Build a single-file executable from main.py.
# Flags:
# --onefile: produce a single bundled executable
# --clean:   clean PyInstaller cache and temporary files before building
# --name:    set the output binary's base name to $SNAPSHOT_NAME
# IMPORTANT: As written, this does NOT embed the 'storage' folder.
# To embed it, add: --add-data "storage:storage"
echo "📄 Building standalone FunKit binary with full storage included..."
pyinstaller main.py --onefile --clean --name "$SNAPSHOT_NAME"

# -----------------------------------------------------------------------------
# Step 4: Move the artifact to the snapshots directory and finalize.
# -----------------------------------------------------------------------------

# Move the built binary from dist/ to $SNAPSHOT_DIR and append .bin for clarity.
# On Unix-like systems, extensions are optional; this is a cosmetic choice.
echo "📁 Moving final binary to $SNAPSHOT_DIR/"
mv "dist/$SNAPSHOT_NAME" "$SNAPSHOT_DIR/$SNAPSHOT_NAME.bin"

# Announce completion and show the final path for convenience.
echo "✅ Snapshot complete: $SNAPSHOT_DIR/$SNAPSHOT_NAME.bin"