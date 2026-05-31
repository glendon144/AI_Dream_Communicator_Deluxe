#!/usr/bin/env bash
set -euo pipefail

GUI="modules/gui_tkinter.py"
[ -f "$GUI" ] || { echo "❌ $GUI not found"; exit 1; }

ts() { date +"%Y%m%d-%H%M%S"; }
cp -p "$GUI" "$GUI.bak.$(ts)"

python3 - "$GUI" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p, 'r', encoding='utf-8', errors='ignore').read()

# 1) Ensure the handler lives on the DemoKitGUI class (not elsewhere).
has_demo = re.search(r"\bclass\s+DemoKitGUI\b", s)
if not has_demo:
    print("⚠️  DemoKitGUI class not found; no changes made.")
    print("   (If your GUI class has a different name, tell me and I’ll adjust the patch.)")
    sys.exit(0)

demo_block = re.search(r"(class\s+DemoKitGUI\b.*?:\s*\n)", s)
if not demo_block:
    print("⚠️  DemoKitGUI definition not matched cleanly; aborting to avoid damage.")
    sys.exit(1)

# Already present?
if re.search(r"\bdef\s+_open_url_to_opml\s*\(self\)\s*:", s):
    # Great — method exists, so nothing to add.
    pass
else:
    insert_at = demo_block.end()
    method = (
        "    def _open_url_to_opml(self):\n"
        "        import tkinter as tk\n"
        "        from tkinter import simpledialog, messagebox\n"
        "        try:\n"
        "            from modules import aopml_engine as eng\n"
        "        except Exception:\n"
        "            import modules.aopmlengine as eng\n"
        "        url = simpledialog.askstring('URL → OPML','Enter a URL to import as OPML:')\n"
        "        if not url:\n"
        "            return\n"
        "        try:\n"
        "            opml = eng.url_to_opml(url)\n"
        "        except Exception as e:\n"
        "            messagebox.showerror('Import failed', str(e))\n"
        "            return\n"
        "        try:\n"
        "            doc_id = self.doc_store.create_document(title=f'OPML from {url}', content=opml, content_type='opml')\n"
        "            self.refresh_list_and_open(doc_id)\n"
        "        except Exception as e:\n"
        "            messagebox.showerror('Save failed', str(e))\n"
        "            return\n\n"
    )
    s = s[:insert_at] + method + s[insert_at:]

# 2) As a safety net, ensure the menu wiring uses the instance method.
# If a previous patch accidentally added a top-level (module) function, keep the existing menu line,
# but this ensures we reference self._open_url_to_opml rather than a stray symbol.
s = re.sub(
    r"(add_command\(label=['\"]URL\s*→\s*Import as OPML['\"],\s*command=)([^\)\n]+)",
    r"\1self._open_url_to_opml",
    s
)

open(p, 'w', encoding='utf-8').write(s)
print("✅ Ensured DemoKitGUI has _open_url_to_opml and menu references the bound method.")
PY

echo "🎉 Done. Try again: python3 main.py"

