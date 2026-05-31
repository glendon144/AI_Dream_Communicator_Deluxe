#!/usr/bin/env bash
set -euo pipefail
f="modules/gui_tkinter.py"
tmp="$(mktemp)"

# 1) Strip ALL existing opml_bridge import blocks and duplicate tkinter imports
#    Also remove any direct PiKit opml_extras_plugin import blocks.
awk '
BEGIN{skip_opml=0; skip_pikit=0}
# Start of any opml_bridge block
/^from modules\.opml_bridge import[[:space:]]*\(/ {skip_opml=1; next}
skip_opml==1 { if ($0 ~ /^\)/) { skip_opml=0; next } else next }

# Start of any direct PiKit opml_extras_plugin block
/^from modules\.pikit_port\.opml_extras_plugin import[[:space:]]*\(/ {skip_pikit=1; next}
skip_pikit==1 { if ($0 ~ /^\)/) { skip_pikit=0; next } else next }

# Drop duplicate tkinter import (we will re-add one)
$0 ~ /^from tkinter import filedialog, messagebox$/ { next }

{ print }
' "$f" > "$tmp"
mv "$tmp" "$f"

# 2) Insert a single canonical import block after the TreeView import (or at top if not found)
awk -v block='from tkinter import filedialog, messagebox
from modules.opml_bridge import (
    export_current_to_opml,
    import_opml_file,
    preview_outline_as_html,
    open_preview,
    install_into_app_if_available,
)
' '
inserted==0 && /^from modules\.TreeView import open_tree_view/ {
    print; print block; inserted=1; next
}
{ print }
END { if (inserted==0) { print block } }
' "$f" > "$tmp"
mv "$tmp" "$f"

python3 -m py_compile "$f" && echo "✅ gui_tkinter.py import block consolidated."
