#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${AI_COMMUNICATOR_PYTHON:-/Users/gross/.venvs/ai_communicator/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python virtual environment not found: $PYTHON_BIN" >&2
  exit 1
fi

"$PYTHON_BIN" -m pip install --upgrade pyinstaller
cd "$ROOT_DIR"
rm -rf build/ai_communicator dist/ai_communicator
"$PYTHON_BIN" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT_DIR/dist/ai_communicator" \
  --workpath "$ROOT_DIR/build/ai_communicator" \
  packaging/ai_communicator.spec

echo "Build complete: $ROOT_DIR/dist/ai_communicator"
