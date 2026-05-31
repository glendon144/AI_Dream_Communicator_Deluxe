#!/usr/bin/env bash
set -euo pipefail

GUI="modules/gui_tkinter.py"
[ -f "$GUI" ] || { echo "❌ $GUI not found"; exit 1; }

ts() { date +"%Y%m%d-%H%M%S"; }
cp -p "$GUI" "$GUI.bak.$(ts)"

python3 - "$GUI" <<'PY'
import re, sys
p=sys.argv[1]
s=open(p,'r',encoding='utf-8',errors='ignore').read()

# 1) Ensure handler exists on the main GUI class (heuristic: first class that subclasses tk.Tk or has __init__ with tk.Menu)
if "_open_url_to_opml(" not in s:
    s = re.sub(
        r"(class\s+\w+\(.*?\):\s*\n)",
        r"\1"
        r"    def _open_url_to_opml(self):\n"
        r"        import tkinter as tk\n"
        r"        from tkinter import simpledialog, messagebox\n"
        r"        try:\n"
        r"            from modules import aopml_engine as eng\n"
        r"        except Exception:\n"
        r"            import modules.aopmlengine as eng\n"
        r"        url = simpledialog.askstring('URL → OPML','Enter a URL to import as OPML:')\n"
        r"        if not url:\n"
        r"            return\n"
        r"        try:\n"
        r"            opml = eng.url_to_opml(url)\n"
        r"        except Exception as e:\n"
        r"            messagebox.showerror('Import failed', str(e))\n"
        r"            return\n"
        r"        try:\n"
        r"            doc_id = self.doc_store.create_document(title=f'OPML from {url}', content=opml, content_type='opml')\n"
        r"            self.refresh_list_and_open(doc_id)\n"
        r"        except Exception as e:\n"
        r"            messagebox.showerror('Save failed', str(e))\n"
        r"            return\n\n",
        s, count=1, flags=re.S
    )

# 2) Try to find a Tools→OPML submenu block and add the command
added = False

# Pattern A: An existing OPML submenu being built off a variable named 'menu'
def add_to_first_opml_block(text):
    return re.sub(
        r"(menu\.add_command\(label=.*?OPML.*?\).*\n)",
        r"\1", text, count=1, flags=re.S
    )

# Look for a menu block that already mentions 'OPML'
m = re.search(r"(?:^|\n)\s*#?.{0,40}OPML.{0,200}?\n", s, flags=re.S|re.I)
if m and "URL → Import as OPML" not in s:
    # Try to inject after the first OPML menu creation we find
    s2, n = re.subn(
        r"(\bmenu\.add_command\(.*?OPML.*?\)\s*\n)",
        r"\1        menu.add_command(label='URL → Import as OPML', command=self._open_url_to_opml)\n",
        s, count=1, flags=re.S
    )
    if n == 0:
        # Try a slightly different anchor: any place a submenu named OPML is created
        s2, n = re.subn(
            r"(\b(opml|OPML)_menu\s*=\s*tk\.Menu\(.*?\)\s*\n)",
            r"\1        \2_menu.add_command(label='URL → Import as OPML', command=self._open_url_to_opml)\n",
            s, count=1, flags=re.S
        )
    if n > 0:
        s, added = s2, True

# 3) If not found, create Tools→OPML and inject the item under it.
if not added and "URL → Import as OPML" not in s:
    # Insert into a typical menubar build (look for a 'Tools' menu creation)
    # Strategy: after the first occurrence of a Tools menu, ensure an OPML cascade exists; if not, create it.
    # Fallback: create a brand-new OPML submenu under Tools.
    # Find a tools_menu var or any menu named Tools
    tools_anchor = re.search(r"(\btools_menu\s*=\s*tk\.Menu\(.*?\)\s*\n(?:.*?\n){0,20}?menu\.add_cascade\(label=['\"]Tools['\"].*?menu=\s*tools_menu\))", s, flags=re.S)
    if tools_anchor:
        idx = tools_anchor.end()
        opml_block = (
            "\n        # OPML submenu (added by patch)\n"
            "        opml_menu = tk.Menu(tools_menu, tearoff=0)\n"
            "        opml_menu.add_command(label='URL → Import as OPML', command=self._open_url_to_opml)\n"
            "        tools_menu.add_cascade(label='OPML', menu=opml_menu)\n"
        )
        s = s[:idx] + opml_block + s[idx:]
        added = True

# 4) Last-resort: add a Tools menu with OPML if neither Tools nor OPML existed
if not added and "URL → Import as OPML" not in s:
    # Find menubar creation (menubar = tk.Menu(self))
    bar = re.search(r"(\bmenubar\s*=\s*tk\.Menu\([^\n]*\)\s*\n)", s)
    if bar:
        idx = bar.end()
        tools_block = (
            "\n        # Tools menu & OPML submenu (added by patch)\n"
            "        tools_menu = tk.Menu(menubar, tearoff=0)\n"
            "        opml_menu = tk.Menu(tools_menu, tearoff=0)\n"
            "        opml_menu.add_command(label='URL → Import as OPML', command=self._open_url_to_opml)\n"
            "        tools_menu.add_cascade(label='OPML', menu=opml_menu)\n"
            "        menubar.add_cascade(label='Tools', menu=tools_menu)\n"
        )
        s = s[:idx] + tools_block + s[idx:]
        added = True

open(p,'w',encoding='utf-8').write(s)
print("✅ Patched GUI: handler present, and menu injected (or created).")
PY

echo "🎉 Done. Launch FunKit and check: Tools → OPML → URL → Import as OPML"

