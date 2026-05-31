#!/usr/bin/env bash
set -euo pipefail
: "${VERBOSE:=0}"

say() { echo -e "$@"; }
run() { [ "$VERBOSE" = "1" ] && set -x; "$@"; [ "$VERBOSE" = "1" ] && set +x; }

DEFAULT_TAG_PREFIX="opml_baseline"
FILES_TO_ADD=()

# Never page inside scripts
export GIT_PAGER=
export PAGER=

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { say "❌ Not a git repo."; exit 1; }

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
HAVE_ORIGIN=1; git remote get-url origin >/dev/null 2>&1 || HAVE_ORIGIN=0

say "📦 Branch: $BRANCH"
say "🌐 Remote 'origin': $([ $HAVE_ORIGIN -eq 1 ] && echo 'present' || echo 'missing')"

# Stage
if [ ${#FILES_TO_ADD[@]} -eq 0 ]; then
  say "➕ Staging all changes (git add -A)…"
  run git add -A
else
  say "➕ Staging specific paths: ${FILES_TO_ADD[*]}"
  run git add "${FILES_TO_ADD[@]}"
fi

say "🧾 Staged diff (stat):"
git --no-pager diff --cached --stat || true
say "🧾 Status (short):"
git --no-pager status -s || true

# Nothing staged?
if git diff --cached --quiet; then
  say "ℹ️  No staged changes. Nothing to commit."
  exit 0
fi

NOW_ISO="$(date -Iseconds)"
COMMIT_MSG="$(cat <<'EOF'
✨ OPML Rendering & TreeView lineage milestone

- Automatic OPML detection and rendering in the document pane.
- Integrated OPML parsing directly into _render_document (BOM-safe).
- Fixed geometry manager conflict (grid vs pack) in OPML view.
- Restored toolbar handlers (e.g., _on_delete_clicked, _handle_image).
- TreeView lineage displays correctly from green links.
- OPML tree depth preference persists until changed by user.

Tagging this as the first stable OPML-capable build of PiKit.
EOF
)"
COMMIT_MSG+="

Committed at: $NOW_ISO
Branch: $BRANCH
"

say "📝 Committing…"
run git commit -m "$COMMIT_MSG"

TAG_BASE="${DEFAULT_TAG_PREFIX}_$(date +%Y%m%d_%H%M)"
TAG="$TAG_BASE"; i=2
while git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; do
  TAG="${TAG_BASE}_$i"; i=$((i+1))
done

say "🔖 Tagging: $TAG"
run git tag -a "$TAG" -m "Snapshot: $TAG"

if [ $HAVE_ORIGIN -eq 1 ]; then
  if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
    say "🚀 Pushing branch to origin…"
    run git push
  else
    say "🚀 First push for $BRANCH (setting upstream)…"
    run git push --set-upstream origin "$BRANCH"
  fi
  say "🚀 Pushing tag $TAG…"
  run git push origin "$TAG"
  say "✅ Done. Branch: $BRANCH, Tag: $TAG"
else
  say "⚠️  No remote. Commit and tag are local.
   To push:
     git remote add origin <URL>
     git push --set-upstream origin $BRANCH
     git push origin $TAG"
fi

