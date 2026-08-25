#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${AI_COMMUNICATOR_PYTHON:-/Users/gross/.venvs/ai_communicator/bin/python}"
PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$ROOT_DIR/.pyinstaller}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python virtual environment not found: $PYTHON_BIN" >&2
  exit 1
fi

# Avoid an unnecessary network dependency when the pinned build environment
# already contains PyInstaller. Set FORCE_PYINSTALLER_UPGRADE=1 to refresh it.
if [[ "${FORCE_PYINSTALLER_UPGRADE:-0}" == "1" ]]; then
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$PYTHON_BIN" -m pip install --upgrade pyinstaller
elif ! "$PYTHON_BIN" -c 'import PyInstaller' >/dev/null 2>&1; then
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$PYTHON_BIN" -m pip install pyinstaller
fi
cd "$ROOT_DIR"
# Finder may leave a .DS_Store at the output root while inspecting a bundle;
# remove the output contents explicitly so cleanup does not abort on that
# directory entry.
mkdir -p build/ai_communicator dist/ai_communicator
find build/ai_communicator dist/ai_communicator -mindepth 1 -maxdepth 1 -exec rm -rf {} +
PYINSTALLER_CONFIG_DIR="$PYINSTALLER_CONFIG_DIR" "$PYTHON_BIN" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT_DIR/dist/ai_communicator" \
  --workpath "$ROOT_DIR/build/ai_communicator" \
  packaging/ai_communicator.spec

# PyInstaller relocates files copied into a macOS framework to its versioned
# Resources directory. QtWebEngineProcess is looked up at the framework-level
# Helpers path, so restore the helper app to the location Qt expects.
APP_DIR="$ROOT_DIR/dist/ai_communicator/ai_dream_communicator_deluxe.app"
QT_DIR="$($PYTHON_BIN -c 'import pathlib, PySide6; print(pathlib.Path(PySide6.__file__).resolve().parent / "Qt")')"
FRAMEWORK_DIR="$APP_DIR/Contents/Frameworks/PySide6/Qt/lib/QtWebEngineCore.framework"

# PyInstaller can flatten framework data into Versions/Resources (and, with
# this framework, Versions/Resources/Resources), leaving the real
# Versions/A/Resources directory incomplete. QtWebEngine's main process and
# QtWebEngineProcess resolve Resources through different framework paths, so
# mirror the complete upstream resource tree into every path that can be
# produced by the build. This includes the architecture-specific V8 startup
# snapshots; copying only the .pak files makes the renderer crash at startup.
SOURCE_RESOURCES="$QT_DIR/lib/QtWebEngineCore.framework/Resources"
RESOURCE_TARGETS=(
  "$FRAMEWORK_DIR/Versions/A/Resources"
  "$FRAMEWORK_DIR/Resources"
)
if [[ -d "$FRAMEWORK_DIR/Versions/Resources/Resources" ]]; then
  RESOURCE_TARGETS+=("$FRAMEWORK_DIR/Versions/Resources/Resources")
fi
for target in "${RESOURCE_TARGETS[@]}"; do
  mkdir -p "$target"
  cp -R "$SOURCE_RESOURCES/." "$target/"
done

HELPER_SOURCE="$(find "$APP_DIR" -type d -path '*/QtWebEngineCore.framework/Versions/Resources/Helpers/QtWebEngineProcess.app' -print -quit)"
if [[ -n "$HELPER_SOURCE" ]]; then
  FRAMEWORK_ROOT="${HELPER_SOURCE%/Versions/Resources/Helpers/QtWebEngineProcess.app}"
  HELPER_DEST="$FRAMEWORK_ROOT/Helpers/QtWebEngineProcess.app"
  # The framework-level Helpers entry normally resolves to Versions/A/Helpers.
  # Replace the destination as one complete app; copying into it a second time
  # creates QtWebEngineProcess.app/QtWebEngineProcess.app and can break helper
  # startup.
  mkdir -p "$FRAMEWORK_ROOT/Versions/A/Helpers"
  rm -rf "$HELPER_DEST"
  cp -R "$HELPER_SOURCE" "$HELPER_DEST"
else
  echo "QtWebEngineProcess helper was not collected in $APP_DIR" >&2
  exit 1
fi

if [[ ! -x "$FRAMEWORK_ROOT/Versions/A/Helpers/QtWebEngineProcess.app/Contents/MacOS/QtWebEngineProcess" ]]; then
  echo "QtWebEngineProcess helper is incomplete after framework repair" >&2
  exit 1
fi
for resource in icudtl.dat v8_context_snapshot.arm64.bin v8_context_snapshot.x86_64.bin qtwebengine_locales/en-US.pak; do
  if [[ ! -f "$FRAMEWORK_DIR/Resources/$resource" ]]; then
    echo "Missing QtWebEngine resource at resolved framework path: $resource" >&2
    exit 1
  fi
done

echo "Build complete: $ROOT_DIR/dist/ai_communicator"
echo "App: $APP_DIR"
