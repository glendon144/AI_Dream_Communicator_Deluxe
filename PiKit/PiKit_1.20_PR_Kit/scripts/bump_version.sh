#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"
ROOT="${2:-.}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version> [repo_root=.]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$SCRIPT_DIR/update_version.py"

echo "Bumping version to $VERSION in $ROOT"
python3 "$PY" "$VERSION" "$ROOT"

pushd "$ROOT" >/dev/null
git add -A
git commit -m "Bump version to $VERSION" || echo "Nothing to commit."
git tag -a "v$VERSION" -m "PiKit $VERSION" || echo "Tag may already exist."
popd >/dev/null

echo "Created/updated tag v$VERSION"
echo "To push:"
echo "  (cd \"$ROOT\" && git push && git push origin v$VERSION)"
