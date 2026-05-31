#!/bin/bash
# save as commit_opml_baseline.sh, then run: bash commit_opml_baseline.sh

set -e

# Stage the updated files (adjust if you edited more than these)
git add modules/gui_tkinter.py modules/TreeView.py

# Commit with a detailed message
git commit -m "✨ OPML Rendering & TreeView lineage milestone

- Added automatic OPML detection and rendering in the document pane.
- Integrated OPML parsing directly into _render_document.
- Fixed geometry manager conflict (grid vs pack) in OPML view.
- Restored missing toolbar handlers (_on_delete_clicked, _handle_image).
- TreeView lineage now displays correctly from green links.
- OPML tree depth preference persists until changed by user.
- Maintained stability with existing image rendering and link features.

Tagging this as the first stable OPML-capable build of FunKit."

# Create an annotated tag for quick reference
git tag -a opml_baseline_v1 -m "First working OPML rendering & TreeView lineage version"

# Push commit and tag to remote
git push
git push origin opml_baseline_v1

echo "✅ Commit and tag completed: opml_baseline_v1"

