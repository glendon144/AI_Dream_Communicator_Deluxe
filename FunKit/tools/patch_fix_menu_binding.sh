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

# 1) Make sure DemoKitGUI exists
cls = re.search(r"(class\s+DemoKitGUI\b.*?:\s*\n)", s)
if not cls:
    print("⚠️  DemoKitGUI class not found; aborting to avoid damage.")
    sys.exit(1)

# 2) Ensure method is defined on DemoKitGUI
if not re.search(r"\bdef\s+_open_url_to_opml\s*\(\s*self\s*\)\s*:", s):
    insert_at = cls.end()
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

# 3) Rebind any menu command to a lambda that closes over self
#    This covers several possible existing forms.
patterns = [
    r"(command\s*=\s*)self\._open_url_to_opml\b",
    r"(command\s*=\s*)_open_url_to_opml\b",
    r"(command\s*=\s*)\w+_menu\.open_url_to_opml\b",
]
for pat in patterns:
    s = re.sub(pat, r"\1lambda s=self: s._open_url_to_opml()", s)

# Also ensure we didn’t accidentally insert parentheses anywhere
s = s.replace("command=self._open_url_to_opml()", "command=lambda s=self: s._open_url_to_opml()")

open(p, 'w', encoding='utf-8').write(s)
print("✅ Bound DemoKitGUI._open_url_to_opml and rewired menu callback to lambda.")
PY

echo "🎉 Done. Now run:  python3 main.py"

