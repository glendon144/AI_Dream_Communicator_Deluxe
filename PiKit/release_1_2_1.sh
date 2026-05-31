#!/usr/bin/env bash
set -euo pipefail

VERSION="1.2.1"
TAG="v${VERSION}"
DATE_UTC="$(date -u +'%Y-%m-%d')"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "Not inside a git repository." >&2; exit 1;
}

CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "==> Preparing release ${TAG} on branch ${CUR_BRANCH}"

# Fetch (ignore failures if no remote)
git fetch --all || true

# Write/refresh VERSION
echo "${VERSION}" > VERSION

# Build release notes safely
NOTES="$(cat <<'EOF'
✨ **PiKit / DemoKit — v1.2.1**

🌐 **URL → OPML importer (async, resilient)**
- Background fetch with timeouts, size caps, and content-type checks
- **Quick** (≈12s/≈600KB) and **Full** (≈25s/≈2.5MB) modes
- **Cancelable** “Fetching URLs…” dialog
- HTML → OPML via engine; **text fallback** if HTML parse fails
- All **database writes on the main thread** (no SQLite thread errors)

🗂️ **SAFE Batch OPML**
- Multi-select docs → **Create OPML copies**; originals are untouched
- Optional header-link insertion (toggle in Preferences)

🧩 **OPML rendering & recovery**
- Embedded OPML tree view with caret expand/collapse
- Fallback renderer for “OPML-ish” text
- “Repair current doc → OPML (overwrite)” and **Batch: Repair selected OPML**

🧹 **Formatting fixes**
- Fixed literal `\n` → real newlines in headers
- Title bar normalization (no more accumulating phase tags)

⚙️ **Preferences**
- After Convert: **Open / Link / Open+Link**
- Batch: **prepend header link** (optional)
- Network/URL: **Quick vs Full** mode toggle

🔒 **Stability**
- Validation of OPML before save; trims leading noise
- GUI remains responsive during network operations

Thanks for the great collaboration! 🚀
EOF
)"

# Prepend to CHANGELOG.md (create if missing)
if [[ -f CHANGELOG.md ]]; then
  TMP_FILE="$(mktemp)"
  {
    echo "## ${TAG} — ${DATE_UTC}"
    echo
    echo "${NOTES}"
    echo
    cat CHANGELOG.md
  } > "${TMP_FILE}"
  mv "${TMP_FILE}" CHANGELOG.md
else
  {
    echo "# Changelog"
    echo
    echo "## ${TAG} — ${DATE_UTC}"
    echo
    echo "${NOTES}"
    echo
  } > CHANGELOG.md
fi

# Stage files
git add VERSION CHANGELOG.md || true

# Commit only if something actually changed
if ! git diff --cached --quiet --exit-code; then
  git commit -m "Release ${TAG}: URL→OPML (async + cancel), SAFE Batch, repairs, prefs, and robustness"
  echo "==> Commit created."
else
  echo "==> No content changes to commit (VERSION/CHANGELOG already up-to-date)."
fi

# Create/update annotated tag
MSG_FILE="$(mktemp)"
printf "PiKit / DemoKit %s — %s\n\n%s\n" "${TAG}" "${DATE_UTC}" "${NOTES}" > "${MSG_FILE}"

if git rev-parse "${TAG}" >/dev/null 2>&1; then
  echo "==> Tag ${TAG} exists; updating it."
  git tag -d "${TAG}" >/dev/null 2>&1 || true
fi
git tag -a "${TAG}" -F "${MSG_FILE}"
rm -f "${MSG_FILE}"

# Push branch and tag (ignore errors if remote missing)
git push origin "${CUR_BRANCH}" || true
git push --tags origin || true

echo "==> Done. Pushed branch '${CUR_BRANCH}' and tag '${TAG}'."
echo "    VERSION set to ${VERSION} and CHANGELOG.md updated."

