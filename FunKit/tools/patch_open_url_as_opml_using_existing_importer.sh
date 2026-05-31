#!/usr/bin/env bash
set -euo pipefail

GUI="modules/gui_tkinter.py"
PLUGIN="modules/opml_extras_plugin.py"

[ -f "$GUI" ] || { echo "❌ $GUI not found"; exit 1; }

ts=$(date +%Y%m%d-%H%M%S)
cp -p "$GUI" "$GUI.bak.$ts"
[ -f "$PLUGIN" ] && cp -p "$PLUGIN" "$PLUGIN.bak.$ts" || true

python3 - <<'PY'
import sys, os, re, io

GUI="modules/gui_tkinter.py"
PLUGIN="modules/opml_extras_plugin.py"

s=open(GUI,encoding="utf-8",errors="ignore").read()

# 1) Ensure DemoKitGUI has _open_url_as_opml that uses EXISTING OPML FILE IMPORTER
if "_open_url_as_opml" not in s:
    m=re.search(r"(class\s+DemoKitGUI\b.*?:\s*\n)", s)
    if not m:
        print("❌ DemoKitGUI class not found in GUI"); sys.exit(1)
    insert_at=m.end()
    block = r'''
    def _open_url_as_opml(self):
        """
        Prompt for URL, convert to OPML, write a temp file, and invoke the GUI's existing
        OPML file importer (no DocumentStore guessing).
        """
        import os, tempfile
        import tkinter.simpledialog as simpledialog, tkinter.messagebox as messagebox
        try:
            from modules import aopml_engine as eng
        except Exception:
            import modules.aopml_engine as eng

        url = simpledialog.askstring("Open URL as OPML", "Enter a URL:")
        if not url:
            return

        try:
            opml_xml = eng.url_to_opml(url)
        except Exception as e:
            messagebox.showerror("URL → OPML failed", str(e))
            return

        # write temp .opml
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix="import_", suffix=".opml")
            os.close(fd)
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(opml_xml)
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not write temp OPML: {e}")
            return

        # Try known importer method names in priority order
        importers = [
            "open_opml_from_path",
            "_open_opml_file",
            "import_opml_from_path",
            "import_opml_file",
            "handle_open_opml_path",
        ]

        doc_id = None
        try:
            # If there is a command processor object with an importer, try it first.
            cp = getattr(self, "command_processor", None)
            if cp and hasattr(cp, "open_opml_from_path"):
                try:
                    doc_id = cp.open_opml_from_path(tmp_path)
                except TypeError:
                    doc_id = cp.open_opml_from_path(path=tmp_path)
        except Exception:
            pass

        if doc_id is None:
            for name in importers:
                fn = getattr(self, name, None)
                if not fn:
                    continue
                try:
                    doc_id = fn(tmp_path)
                except TypeError:
                    try:
                        doc_id = fn(path=tmp_path)
                    except Exception:
                        continue
                except Exception:
                    continue
                if doc_id is not None:
                    break

        if doc_id is not None:
            try:
                # Common refresh/open paths in FunKit
                if hasattr(self, "refresh_list_and_open"):
                    self.refresh_list_and_open(doc_id)
                elif hasattr(self, "_refresh_sidebar") and hasattr(self, "doc_store") and hasattr(self.doc_store, "get_document"):
                    self._refresh_sidebar()
                    self._render_document(self.doc_store.get_document(doc_id))
            except Exception:
                pass
        else:
            # No importer found — tell the user where the file is so they can use "Open OPML"
            try:
                messagebox.showinfo("OPML Saved",
                                    f"Saved OPML to:\n{tmp_path}\n\nUse your existing Open OPML action to load it.")
            except Exception:
                print("[URL->OPML] Saved OPML to:", tmp_path)
    '''
    s = s[:insert_at] + block + s[insert_at:]

# 2) After menubar is configured, attach the plugin explicitly
if "opml_extras_plugin.attach(self)" not in s:
    s = re.sub(
        r"(self\.config\(menu=menubar\)\s*)",
        r"""\1
        # Attach OPMLExtras plugin explicitly (adds Tools → OPML → Open URL as OPML)
        try:
            from modules import opml_extras_plugin
            opml_extras_plugin.attach(self)
        except Exception as e:
            print("[WARN] OPMLExtras attach failed:", e)
""",
        s, count=1
    )

open(GUI,"w",encoding="utf-8").write(s)

# 3) Ensure plugin file exists and calls the method on the GUI instance
if not os.path.exists(PLUGIN):
    os.makedirs(os.path.dirname(PLUGIN), exist_ok=True)
    open(PLUGIN,"w",encoding="utf-8").write('''# modules/opml_extras_plugin.py
import tkinter as tk

def attach(gui):
    """
    Add Tools → OPML → Open URL as OPML, bound to gui._open_url_as_opml().
    """
    menubar = getattr(gui, "menubar", None)
    if menubar is None:
        return

    # Find an existing Tools menu
    tools_menu = None
    end = menubar.index("end") or -1
    for i in range(end + 1):
        try:
            if menubar.type(i) == "cascade" and menubar.entrycget(i, "label") == "Tools":
                tools_menu = menubar.nametowidget(menubar.entrycget(i, "menu"))
                break
        except Exception:
            pass

    # Create Tools if missing
    if tools_menu is None:
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)

    # Add OPML submenu
    opml_menu = tk.Menu(tools_menu, tearoff=0)
    opml_menu.add_command(label="Open URL as OPML", command=lambda s=gui: s._open_url_as_opml())
    tools_menu.add_cascade(label="OPML", menu=opml_menu)
''')
else:
    # If a plugin exists, ensure its command calls the bound instance method
    plug = open(PLUGIN,encoding="utf-8",errors="ignore").read()
    if "_open_url_as_opml" not in plug:
        plug = re.sub(
            r"(add_command\(label=.*?(Open URL as OPML|URL.*OPML).*?command\s*=\s*)([^\)]*)\)",
            r"\1lambda s=gui: s._open_url_as_opml())",
            plug, flags=re.I|re.S
        )
        open(PLUGIN,"w",encoding="utf-8").write(plug)

print("✅ Patched GUI + plugin to use existing OPML file importer.")
PY

echo "Done."

