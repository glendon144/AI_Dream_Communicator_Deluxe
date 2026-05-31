#!/usr/bin/env bash
set -euo pipefail
GUI="modules/gui_tkinter.py"
[ -f "$GUI" ] || { echo "❌ $GUI not found"; exit 1; }
cp -p "$GUI" "$GUI.bak.$(date +%Y%m%d-%H%M%S)"

python3 - "$GUI" <<'PY'
import re, sys
p=sys.argv[1]
s=open(p,'r',encoding='utf-8',errors='ignore').read()

# 1) Ensure DemoKitGUI class exists
m=re.search(r"(class\s+DemoKitGUI\b.*?:\s*\n)", s)
if not m:
    print("⚠️ DemoKitGUI not found; aborting.")
    sys.exit(1)

insert_at=m.end()

# 2) Ensure the real worker exists (idempotent)
if not re.search(r"\bdef\s+_open_url_to_opml\s*\(\s*self\s*\)\s*:", s):
    s = s[:insert_at] + (
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
        "        opml = eng.url_to_opml(url)\n"
        "        doc_id = self.doc_store.create_document(title=f'OPML from {url}', content=opml, content_type='opml')\n"
        "        self.refresh_list_and_open(doc_id)\n\n"
    ) + s[insert_at:]

# 3) Add a debug wrapper that surfaces exceptions
if not re.search(r"\bdef\s+_debug_url_to_opml\s*\(\s*self\s*\)\s*:", s):
    s = s[:insert_at] + (
        "    def _debug_url_to_opml(self):\n"
        "        import traceback\n"
        "        from tkinter import messagebox\n"
        "        try:\n"
        "            print('[URL→OPML] menu clicked')\n"
        "            self.after(0, lambda: None)  # ensure we’re in mainloop\n"
        "            self._open_url_to_opml()\n"
        "        except Exception as e:\n"
        "            tb = traceback.format_exc()\n"
        "            print('[URL→OPML] ERROR:', tb)\n"
        "            try:\n"
        "                messagebox.showerror('URL → OPML failed', tb)\n"
        "            except Exception:\n"
        "                pass\n\n"
    ) + s[insert_at:]

# 4) Rebind any menu command variants to the debug wrapper
patterns = [
    r"(add_command\([^)]*label\s*=\s*['\"]URL\s*[→>-]\s*Import\s+as\s+OPML['\"][^)]*command\s*=\s*)([^)\n]+)",
    r"(add_command\([^)]*label\s*=\s*['\"]URL\s*(?:to|→)\s*OPML['\"][^)]*command\s*=\s*)([^)\n]+)",
]
for pat in patterns:
    s = re.sub(pat, r"\1lambda s=self: s._debug_url_to_opml()", s, flags=re.I)

open(p,'w',encoding='utf-8').write(s)
print("✅ Instrumented: bound menu to _debug_url_to_opml and ensured handler exists.")
PY

echo "🎉 Done. Now run: python3 main.py"

