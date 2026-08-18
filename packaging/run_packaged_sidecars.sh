#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="${1:-$ROOT_DIR/dist/ai_communicator}"
RUNTIME_HOME="${AI_COMMUNICATOR_RUNTIME_HOME:-${TMPDIR:-/tmp}/ai_communicator_home}"
mkdir -p "$RUNTIME_HOME"
export HOME="$RUNTIME_HOME"
export PYINSTALLER_CHECK_HOME="$HOME"

"$PACKAGE_DIR/pikit/pikit" --packaged-smoke-test
"$PACKAGE_DIR/funkit/funkit" --packaged-smoke-test
