#!/usr/bin/env bash
# commit_and_push_opml.sh
# Create/update CHANGELOG.md with milestone notes, commit, tag, and push.

set -euo pipefail

MILESTONE_NOTES=$(cat <<'EOF'
## ✨ OPML Rendering & TreeView lineage milestone — 2025-08-07

- Automatic OPML detection and rendering in the document pane.
- Integrated OPML parsing directly into _render_document (BOM-safe).
- Fixed geometry manager conflict (grid vs pack) in OPML view.
- Restored toolbar handlers (e.g., _on_delete_clicked, _handle_image).
- TreeView lineage displays correctly from green links.
- OPML tree depth preference persists until changed by user.

Tagging this as the first stable OPML-capable build of PiKit.
EOF
)

# Ensure we are in repo
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    echo "❌ Not in a git repository."
    exit 1
}

# Create or prepend to CHANGELOG.md
if [[ -f CHANGELOG.md ]]; then
    echo -e "$MILESTONE_NOTES\n\n$(cat CHANGELOG.md)" > CHANGELOG.md
else
    echo -e "$MILESTONE_NOTES\n" > CHANGELOG.md
fi

# Stage everything
git add -A

# Bail if nothing staged
if git diff --cached --quiet; then
    echo "ℹ️ No changes to commit."
    exit 0
fi

# Commit
NOW="$(date -Iseconds)"
git commit -m "✨ OPML Rendering & TreeView lineage milestone" -m "$NOW"

# Create unique tag
TAG_BASE="opml_baseline_$(date +%Y%m%d_%H%M)"
TAG="$TAG_BASE"
i=2
while git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; do
    TAG="${TAG_BASE}_$i"
    i=$((i+1))
done
git tag -a "$TAG" -m "Snapshot: $TAG"

# Push branch + tag
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if git remote get-url origin >/dev/null 2>&1; then
    if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
        git push
    else
        git push --set-upstream origin "$BRANCH"
    fi
    git push origin "$TAG"
    echo "✅ Pushed branch '$BRANCH' and tag '$TAG'."
else
    echo "⚠️ No remote 'origin' configured. Commit and tag are local."
fi

