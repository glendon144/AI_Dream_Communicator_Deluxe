#!/usr/bin/env bash
set -euo pipefail

VERSION="1.2.2"
BRANCH="main"

echo "==> Preparing release v${VERSION} on branch ${BRANCH}"

git fetch origin
git checkout "${BRANCH}"
git pull --rebase origin "${BRANCH}"

# Warn if there are uncommitted changes, but proceed
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "⚠️  You have uncommitted changes. They'll be included in this release."
fi

# Ensure files exist
[[ -f CHANGELOG.md ]] || touch CHANGELOG.md
echo "${VERSION}" > VERSION

TS="$(date -u +'%Y-%m-%d')"
NL=$'\n'
NOTES="## v${VERSION} — ${TS}${NL}
- 🌐 **URL → OPML**: multi-URL input (spaces, commas, semicolons, newlines), auto \`https://\`, bracket stripping; ASCII User-Agent (fixes header encoding error). 
- 🧵 **Thread-safe DB writes**: all SQLite writes are marshalled to the Tk main thread (no more cross-thread sqlite errors).
- 🧰 **OPML menu + hotkeys**: URL → OPML (Ctrl+U), Convert Selection → OPML (Ctrl+Shift+O / Ctrl+Alt+O / F6), Batch: Convert Selected → OPML (Shift+F6).
- 🧱 **Toolbar integration**: exposing \`self.toolbar\` lets plugins add URL → OPML / Convert → OPML / Batch → OPML buttons.
- 🧹 Polish: safer exporters, better OPML rendering, fewer surprises on binary docs.
"

tmpfile="$(mktemp)"
printf '%s\n\n%s' "$NOTES" "$(cat CHANGELOG.md)" > "$tmpfile"
mv "$tmpfile" CHANGELOG.md

git add -A
git commit -m "chore(release): v${VERSION} – URL→OPML fixes, thread-safe DB, OPML menu & batch convert"

# Create/refresh tag locally
if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
  git tag -d "v${VERSION}" >/dev/null 2>&1 || true
fi
git tag -a "v${VERSION}" -m "FunKit v${VERSION}"

# Push
git push origin "${BRANCH}"
set +e
git push origin "v${VERSION}"
if [[ $? -ne 0 ]]; then
  echo "ℹ️  Tag v${VERSION} already exists on remote; keeping local tag."
fi
set -e

echo "==> Done. Pushed ${BRANCH} and tag v${VERSION}."
echo "    VERSION set to ${VERSION} and CHANGELOG.md updated."

