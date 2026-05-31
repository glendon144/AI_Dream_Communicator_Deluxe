#!/usr/bin/env bash
# Commit + tag + push with upstream auto-setup.
# Usage: bash commit_opml.sh
# Tip: chmod +x commit_opml.sh && ./commit_opml.sh

set -euo pipefail

# ---- Config ---------------------------------------------------------------
DEFAULT_TAG_PREFIX="opml_baseline"
FILES_TO_ADD=()   # empty means "git add -A" (everything). Put paths here to restrict.
# --------------------------------------------------------------------------

# Ensure we are inside a git repo
git rev-parse --is-inside-work-tree > /dev/null 2>&1 || {
  echo "❌ Not inside a git repository."
  exit 1
}

# Figure out branch + remote
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
REMOTE_OK=true
if ! git remote get-url origin >/dev/null 2>&1; then
  REMOTE_OK=false
fi

# Stage changes
if [ ${#FILES_TO_ADD[@]} -eq 0 ]; then
  git add -A
else
  git add "${FILES_TO_ADD[@]}"
fi

# If nothing staged, bail politely
if git diff --cached --quiet; then
  echo "ℹ️  No staged changes. Nothing to commit."
  exit 0
fi

# Build commit message
NOW_ISO="$(date -Iseconds)"
read -r -d '' COMMIT_MSG <<'EOF'
✨ OPML Rendering & TreeView lineage milestone

- Automatic OPML detection and rendering in the document pane.
- Integrated OPML parsing directly into _render_document (BOM-safe).
- Fixed geometry manager conflict (grid vs pack) in OPML view.
- Restored toolbar handlers (e.g., _on_delete_clicked, _handle_image).
- TreeView lineage displays correctly from green links.
- OPML tree depth preference persists until changed by user.

Tagging this as the first stable OPML-capable build of FunKit.
EOF

# Append timestamp/footer to commit body (helps future archaeology)
COMMIT_MSG="$COMMIT_MSG

Committed at: $NOW_ISO
Branch: $BRANCH
"

# Commit
git commit -m "$COMMIT_MSG"

# Create a unique tag (avoids collisions if rerun)
# Format: opml_baseline_YYYYMMDD_HHMM (or bump a suffix if exists)
TAG_BASE="${DEFAULT_TAG_PREFIX}_$(date +%Y%m%d_%H%M)"
TAG="$TAG_BASE"
i=2
while git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; do
  TAG="${TAG_BASE}_$i"
  i=$((i+1))
done

git tag -a "$TAG" -m "Snapshot: $TAG"

# Push (set upstream if needed)
if $REMOTE_OK; then
  if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
    # Upstream already set
    git push
  else
    # First push for this branch
    git push --set-upstream origin "$BRANCH"
  fi

  # Push tag
  git push origin "$TAG"
  echo "✅ Pushed branch '$BRANCH' and tag '$TAG'."
else
  echo "⚠️  No 'origin' remote configured. Your commit and tag are local:"
  echo "    - Commit on branch: $BRANCH"
  echo "    - Tag: $TAG"
  echo "    To set a remote and push:"
  echo "      git remote add origin <YOUR_REMOTE_URL>"
  echo "      git push --set-upstream origin $BRANCH"
  echo "      git push origin $TAG"
fi

