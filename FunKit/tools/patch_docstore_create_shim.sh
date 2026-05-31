#!/usr/bin/env bash
set -euo pipefail
GUI="modules/gui_tkinter.py"
[ -f "$GUI" ] || { echo "❌ $GUI not found"; exit 1; }
cp -p "$GUI" "$GUI.bak.$(date +%Y%m%d-%H%M%S)"

python3 - "$GUI" <<'PY'
import re, sys
p=sys.argv[1]
s=open(p,encoding='utf-8',errors='ignore').read()

# 1) Insert a portable creator + file fallback into DemoKitGUI
cls = re.search(r"(class\s+DemoKitGUI\b.*?:\s*\n)", s)
if not cls:
    print("❌ DemoKitGUI not found"); sys.exit(1)
insert_at = cls.end()

if "def _create_doc_portable(" not in s:
    block = '''
    def _create_doc_portable(self, title: str, content: str, content_type: str = "opml"):
        """
        Try multiple DocumentStore APIs to create a new doc.
        Falls back to Save As... if none match.
        Returns doc_id or None if saved as file.
        """
        ds = getattr(self, "doc_store", None)
        tried = []
        if ds is None:
            return None
        # candidates: (method_name, kwargs)
        candidates = [
            ("create_document", {"title": title, "content": content, "content_type": content_type}),
            ("add_document",    {"title": title, "content": content, "content_type": content_type}),
            ("new_document",    {"title": title, "content": content, "content_type": content_type}),
            ("create",          {"title": title, "content": content, "content_type": content_type}),
            ("insert_document", {"title": title, "content": content, "content_type": content_type}),
        ]
        for name, kwargs in candidates:
            meth = getattr(ds, name, None)
            if meth is None:
                continue
            try:
                return meth(**kwargs)
            except TypeError:
                # try simpler signatures
                try:
                    return meth(title, content, content_type)
                except Exception as e:
                    tried.append(f"{name} -> {e!r}")
                    continue
            except Exception as e:
                tried.append(f"{name} -> {e!r}")
                continue

        # last resort: if there is update_document and a way to allocate an id
        alloc = getattr(ds, "allocate_document_id", None) or getattr(ds, "create_empty_document", None)
        updater = getattr(ds, "update_document", None)
        if alloc and updater:
            try:
                doc_id = alloc(title=title, content_type=content_type) if alloc.__code__.co_argcount>1 else alloc()
                updater(doc_id, title=title, content=content, content_type=content_type)
                return doc_id
            except Exception as e:
                tried.append(f"allocate+update -> {e!r}")

        # Fallback: Save As... file and let user open via OPEN OPML
        try:
            import tkinter as tk
            from tkinter import filedialog, messagebox
            path = filedialog.asksaveasfilename(
                title="Save OPML",
                defaultextension=".opml",
                filetypes=[("OPML files","*.opml"), ("All files","*.*")]
            )
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                messagebox.showinfo("Saved", f"OPML saved to: {path}\\nUse OPEN OPML to import if needed.")
        except Exception:
            pass
        print("[doc-store] create fell back. Tried:", "; ".join(tried))
        return None
    '''
    s = s[:insert_at] + block + s[insert_at:]

# 2) Make _open_url_to_opml use the portable creator
s = re.sub(
    r"doc_id\s*=\s*self\.doc_store\.create_document\([^)]*\)",
    "doc_id = self._create_doc_portable(title=f'OPML from {url}', content=opml, content_type='opml')",
    s
)

# If the line didn't exist exactly, add a robust try around any remaining creation attempt
if "self._create_doc_portable(" not in s:
    s = re.sub(
        r"(opml\s*=\s*eng\.url_to_opml\(url\).*?\n\s*)(.*?refresh_list_and_open\(.*?\).*)",
        r"\1doc_id = self._create_doc_portable(title=f'OPML from {url}', content=opml, content_type='opml')\n"
        r"        if doc_id is not None:\n"
        r"            \2\n"
        r"        else:\n"
        r"            print('[URL->OPML] Saved to file (no doc created)')\n",
        s, flags=re.S
    )

open(p,'w',encoding='utf-8').write(s)
print("✅ Added portable doc creation with Save-As fallback.")
PY

