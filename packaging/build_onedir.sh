#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${AI_COMMUNICATOR_PYTHON:-/Users/gross/.venvs/ai_communicator/bin/python}"
PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$ROOT_DIR/.pyinstaller}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python virtual environment not found: $PYTHON_BIN" >&2
  exit 1
fi

PIP_DISABLE_PIP_VERSION_CHECK=1 "$PYTHON_BIN" -m pip install --upgrade pyinstaller
cd "$ROOT_DIR"
rm -rf build/ai_communicator dist/ai_communicator
PYINSTALLER_CONFIG_DIR="$PYINSTALLER_CONFIG_DIR" "$PYTHON_BIN" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT_DIR/dist/ai_communicator" \
  --workpath "$ROOT_DIR/build/ai_communicator" \
  packaging/ai_communicator.spec

echo "Build complete: $ROOT_DIR/dist/ai_communicator"
echo "Navigator: $ROOT_DIR/dist/ai_communicator/ai_navigator/ai_navigator"
