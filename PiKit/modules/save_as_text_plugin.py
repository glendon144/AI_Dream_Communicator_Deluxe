"""
save_as_text_plugin.py — Drop-in plugin for PiKit/DemoKit

Adds TWO paths for text:
  1) Export → file dialog (keeps your current "SAVE AS TEXT" behavior)
  2) Convert in DB → replaces body with plain text (or creates a copy)

Also binds convenient hotkeys:
  • Ctrl+Shift+T        → Convert current doc → Text (in place)
  • Ctrl+Alt+Shift+T    → Convert current doc → Text (duplicate new doc)

Install:
    # main.py (after creating the app)
    from modules.save_as_text_plugin import install_save_as_text_into_app
    install_save_as_text_into_app(app)
"""

from __future__ import annotations
from typing import Any

def _is_opml_text(s: Any) -> bool:
    return isinstance(s, str) and "<opml" in s.lower()

def _flatten_opml_to_text(xml_text: str) -> str:
    """Turn OPML XML into an indented bullet list."""
    import xml.etree.ElementTree as ET
    try:
        s = xml_text.lstrip("\ufeff\r\n\t ")
        if "<" in s:
            s = s[s.find("<"):]
        root = ET.fromstring(s)
    except Exception:
        return xml_text  # fall back if not valid XML

    lines: list[str] = []

    def walk(node, depth=0):
        tag = (getattr(node, "tag", "") or "").lower()
        if tag.endswith("outline"):
            text = node.attrib.get("text") or node.attrib.get("title") or ""
            if text:
                lines.append(("  " * depth) + "- " + text)
            for child in list(node):
                walk(child, depth + 1)

    body = root.find(".//body")
    nodes = list(body) if body is not None else list(root)
    for n in nodes:
        walk(n, 0)
    return "\n".join(lines).strip()

def _document_to_plain_text(app, doc) -> str:
    """Return a plain-text representation of the given document (title/body tuple or dict)."""
    # title/body from dict or tuple
    if isinstance(doc, dict):
        title = doc.get("title")
        body = doc.get("body")
    else:
        title = (doc[1] if len(doc) > 1 else "Document")
        body  = (doc[2] if len(doc) > 2 else "")

    # Binary → text
    if isinstance(body, (bytes, bytearray)):
        try:
            from modules.hypertext_parser import render_binary_as_text  # type: ignore
        except Exception:
            render_binary_as_text = None  # type: ignore
        if render_binary_as_text is not None:
            try:
                return render_binary_as_text(body, title or "Document")
            except Exception:
                pass
        try:
            return body.decode("utf-8", errors="replace")
        except Exception:
            return str(body)

    s = (body or "").strip()

    # OPML → bullets
    if _is_opml_text(s):
        return _flatten_opml_to_text(s)

    # HTML → text (light scrub)
    import re
    low = s.lower()
    if ("<html" in low) or ("<body" in low) or ("<div" in low):
        s = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", s, flags=re.I)
        s = re.sub(r"<[^>]+>", " ", s)
    return s.strip()

def _save_current_as_text(self):
    """Export the current document to a .txt file (file dialog)."""
    try:
        from tkinter import filedialog, messagebox
    except Exception:
        return

    if getattr(self, "current_doc_id", None) is None:
        messagebox.showwarning("Save As Text", "No document selected.")
        return

    doc = self.doc_store.get_document(self.current_doc_id)
    if not doc:
        messagebox.showerror("Save As Text", "Document not found.")
        return

    # Default filename
    if isinstance(doc, dict):
        title = doc.get("title") or "Document"
    else:
        title = (doc[1] if len(doc) > 1 else "Document") or "Document"
    safe = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in title).strip() or "Document"
    default_name = f"{safe}.txt"

    text_out = _document_to_plain_text(self, doc)

    path = filedialog.asksaveasfilename(
        title="Save As Text",
        defaultextension=".txt",
        initialfile=default_name,
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    if not path:
        return

    try:
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write((text_out or "") + "\n")
        messagebox.showinfo("Save As Text", f"Saved:\n{path}")
    except Exception as e:
        messagebox.showerror("Save As Text", f"Could not save:\n{e}")

def _convert_current_to_text_inplace(self, duplicate: bool = False):
    """Convert current doc body → plain text and write back to DB.
       If duplicate=True, create a new '(Text)' doc instead of overwriting.
    """
    try:
        from tkinter import messagebox
    except Exception:
        messagebox = None

    if getattr(self, "current_doc_id", None) is None:
        if messagebox: messagebox.showwarning("Convert to Text", "No document selected.")
        return

    doc = self.doc_store.get_document(self.current_doc_id)
    if not doc:
        if messagebox: messagebox.showerror("Convert to Text", "Document not found.")
        return

    # Read id/title/body from dict or tuple
    if isinstance(doc, dict):
        did   = doc.get("id")
        title = doc.get("title") or "Document"
        body  = doc.get("body")
    else:
        did   = doc[0] if len(doc) > 0 else None
        title = doc[1] if len(doc) > 1 else "Document"
        body  = doc[2] if len(doc) > 2 else ""

    text_out = _document_to_plain_text(self, doc)

    try:
        if duplicate:
            new_title = f"{title} (Text)"
            new_id = self.doc_store.add_document(new_title, text_out)
            # open the newly created doc
            if hasattr(self, "_on_link_click"):
                self._on_link_click(new_id)
            else:
                self.current_doc_id = new_id
                if hasattr(self, "_render_document"):
                    self._render_document(self.doc_store.get_document(new_id))
            if messagebox: messagebox.showinfo("Convert to Text", f"Created copy:\n{new_title}")
        else:
            # overwrite current body
            self.doc_store.update_document(did, text_out)
            # refresh current view
            if hasattr(self, "_render_document"):
                self._render_document(self.doc_store.get_document(did))
            if messagebox: messagebox.showinfo("Convert to Text", "Document body converted to plain text.")
    except Exception as e:
        if messagebox: messagebox.showerror("Convert to Text", f"Database error:\n{e}")
        return

def attach_save_as_text_plugin(DemoKitGUI_cls):
    """Attach methods to DemoKitGUI class so toolbar/menu can call them."""
    setattr(DemoKitGUI_cls, "_save_current_as_text", _save_current_as_text)
    setattr(DemoKitGUI_cls, "_convert_current_to_text_inplace", _convert_current_to_text_inplace)

    # Back-compat aliases
    for alias in ("_save_as_text", "_save_text", "_export_as_text"):
        if not hasattr(DemoKitGUI_cls, alias):
            setattr(DemoKitGUI_cls, alias, _save_current_as_text)

    # Expose helpers
    setattr(DemoKitGUI_cls, "_is_opml_text", staticmethod(_is_opml_text))
    setattr(DemoKitGUI_cls, "_flatten_opml_to_text", staticmethod(_flatten_opml_to_text))
    setattr(DemoKitGUI_cls, "_document_to_plain_text", _document_to_plain_text)

def _rewire_or_add_buttons(app) -> int:
    """
    Find a 'SAVE AS TEXT' button and rebind it.
    Also try to add a sibling button 'CONVERT TO TEXT (DB)' next to it.
    Returns how many UI elements were touched.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return 0

    touched = 0
    def _walk(w):
        nonlocal touched
        try:
            children = w.winfo_children()
        except Exception:
            children = []
        for c in children:
            try:
                txt = c.cget("text") if hasattr(c, "cget") else None
            except Exception:
                txt = None

            parent = c.nametowidget(c.winfo_parent()) if hasattr(c, "winfo_parent") else None

            if txt and isinstance(txt, str) and txt.strip().upper() == "SAVE AS TEXT":
                try:
                    c.configure(command=lambda a=app: a._save_current_as_text())
                    touched += 1
                    # try to add a neighbor button
                    try:
                        if parent is not None:
                            btn = ttk.Button(parent, text="CONVERT TO TEXT (DB)", command=lambda a=app: a._convert_current_to_text_inplace(False))
                            # pack/place next to the existing button (best-effort)
                            try:
                                btn.pack(side="left", padx=2)
                            except Exception:
                                btn.grid(row=c.grid_info().get('row', 0), column=c.grid_info().get('column', 0)+1, padx=2, sticky="w")
                            touched += 1
                    except Exception:
                        pass
                except Exception:
                    pass
            _walk(c)
    _walk(app)
    return touched

def install_save_as_text_into_app(app) -> None:
    """Instance-level installer: attach methods, wire buttons, and bind hotkeys."""
    cls = app.__class__
    attach_save_as_text_plugin(cls)

    # Wire any existing "SAVE AS TEXT" buttons & try to add "CONVERT TO TEXT (DB)"
    try:
        _ = _rewire_or_add_buttons(app)
    except Exception as e:
        print("[WARN] SaveAsText plugin: toolbar wiring failed:", e)

    # Hotkeys
    try:
        app.bind_all("<Control-Shift-t>", lambda e: app._convert_current_to_text_inplace(False))
        app.bind_all("<Control-Alt-Shift-t>", lambda e: app._convert_current_to_text_inplace(True))
    except Exception as e:
        print("[WARN] SaveAsText plugin: key bindings failed:", e)
