"""
OPML Extras Plugin for PiKit/DemoKit

Adds an "OPML" menu with:
  • Convert → OPML                (convert current/open doc)
  • Batch Convert Selected → OPML (convert ALL selected docs)
  • URL → OPML                    (fetch a URL and convert)
  • Crawl OPML (recursive)…       (use opml_crawler_adapter to crawl & import)

Install at startup with:
    from modules.opml_extras_plugin import install_opml_extras_into_app
    install_opml_extras_into_app(app)
"""

from __future__ import annotations

import traceback
from typing import Optional

# Tk
try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog as SD
except Exception:  # pragma: no cover
    tk = None
    messagebox = None
    SD = None

# ---- Engine import (canonical: modules.aopmlengine) ----
def _import_engine():
    import importlib
    # Standardize on lowercase module in the package
    return importlib.import_module("modules.aopmlengine")  # Deepseek modified version has _ 

def _convert_payload_to_opml(title: str, payload) -> str:
    """
    Use the engine's preferred API if available, otherwise fall back to legacy helpers.
    """
    eng = _import_engine()
    if hasattr(eng, "convert_payload_to_opml"):
        return eng.convert_payload_to_opml(title, payload)

    # Legacy fallback
    text = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload or "")
    low = text.lower()
    if ("<html" in low or "<body" in low or "<div" in low or "<p" in low) and hasattr(eng, "build_opml_from_html"):
        return eng.build_opml_from_html(title, text)
    if hasattr(eng, "build_opml_from_text"):
        return eng.build_opml_from_text(title, text)
    raise RuntimeError("aopmlengine has no recognized converter (need convert_payload_to_opml or build_opml_from_*)")


# ----------------------- Actions -----------------------

def _convert_current_to_opml(self):
    """Convert the current document to OPML and store as a new document."""
    try:
        if getattr(self, "current_doc_id", None) is None:
            if messagebox:
                messagebox.showinfo("Convert → OPML", "No document is active/selected.")
            return
        doc_id = int(self.current_doc_id)
        doc = self.doc_store.get_document(doc_id)
        if not doc:
            if messagebox:
                messagebox.showerror("Convert → OPML", f"Document {doc_id} not found.")
            return

        # Normalize
        if isinstance(doc, dict):
            title = doc.get("title") or "Document"
            body  = doc.get("body") or ""
        else:
            title = doc[1] if len(doc) > 1 else "Document"
            body  = doc[2] if len(doc) > 2 else ""

        xml = _convert_payload_to_opml(title, body)
        new_id = self.doc_store.add_document(f"{title} (OPML)", xml)

        # Refresh index and focus new doc if possible
        for rf in ("refresh_index", "_refresh_sidebar"):
            try:
                getattr(self, rf)()
                break
            except Exception:
                pass
        try:
            if hasattr(self, "_select_tree_item_for_doc"):
                self._select_tree_item_for_doc(new_id)
        except Exception:
            pass

        if messagebox:
            messagebox.showinfo("Convert → OPML", "Converted 1 document.")
    except Exception as e:
        if messagebox:
            messagebox.showerror("Convert → OPML", f"Conversion failed:\n{e}\n\n{traceback.format_exc()}")
        else:
            print("[Convert→OPML] failed:", e)
            print(traceback.format_exc())


def _batch_convert_selected_to_opml(self):
    """Convert ALL selected documents to OPML and store each as a new document."""
    try:
        tv = getattr(self, "sidebar", None)
        if not tv or not hasattr(tv, "selection"):
            if messagebox:
                messagebox.showerror("Batch Convert → OPML", "Sidebar selection not available.")
            return
        iids = list(tv.selection())
        if not iids:
            if messagebox:
                messagebox.showinfo("Batch Convert → OPML", "No documents selected.")
            return

        converted = failed = 0
        for iid in iids:
            try:
                vals = tv.item(iid, "values") or []
                if not vals:
                    continue
                doc_id = int(vals[0])
                doc = self.doc_store.get_document(doc_id)
                if not doc:
                    continue

                if isinstance(doc, dict):
                    title = doc.get("title") or "Document"
                    body  = doc.get("body") or ""
                else:
                    title = doc[1] if len(doc) > 1 else "Document"
                    body  = doc[2] if len(doc) > 2 else ""

                xml = _convert_payload_to_opml(title, body)
                self.doc_store.add_document(f"{title} (OPML)", xml)
                converted += 1
            except Exception as e:
                print("[Batch OPML] failed for doc:", vals[0] if 'vals' in locals() and vals else '?', e)
                print(traceback.format_exc())
                failed += 1

        # Refresh index after batch
        for rf in ("refresh_index", "_refresh_sidebar"):
            try:
                getattr(self, rf)()
                break
            except Exception:
                pass

        if messagebox:
            if failed:
                messagebox.showwarning("Batch Convert → OPML",
                                       f"Converted {converted} document(s); {failed} failed.")
            else:
                messagebox.showinfo("Batch Convert → OPML",
                                    f"Converted {converted} document(s).")
    except Exception as e:
        if messagebox:
            messagebox.showerror("Batch Convert → OPML", f"Unexpected error:\n{e}\n\n{traceback.format_exc()}")
        else:
            print("[Batch Convert] unexpected error:", e)
            print(traceback.format_exc())


def _import_url_as_opml(self):
    """Prompt for a URL, fetch it via urllib, convert, and store."""
    import urllib.request
    try:
        if not SD:
            if messagebox:
                messagebox.showerror("URL → OPML", "tkinter.simpledialog not available.")
            return
        url = SD.askstring("URL → OPML", "Enter a URL to import as OPML:", parent=self)
        if not url:
            return
        try:
            with urllib.request.urlopen(url, timeout=25) as resp:
                data = resp.read()
        except Exception as e:
            if messagebox:
                messagebox.showerror("URL → OPML", f"Fetch failed:\n{e}")
            return

        xml = _convert_payload_to_opml(url, data)
        new_id = self.doc_store.add_document(f"OPML: {url}", xml)

        for rf in ("refresh_index", "_refresh_sidebar"):
            try:
                getattr(self, rf)()
                break
            except Exception:
                pass
        try:
            if hasattr(self, "_select_tree_item_for_doc"):
                self._select_tree_item_for_doc(new_id)
        except Exception:
            pass

        if messagebox:
            messagebox.showinfo("URL → OPML", "Imported 1 document.")
    except Exception as e:
        if messagebox:
            messagebox.showerror("URL → OPML", f"Import failed:\n{e}\n\n{traceback.format_exc()}")
        else:
            print("[URL→OPML] failed:", e)
            print(traceback.format_exc())


def _crawl_opml_recursive(self):
    """Recursively crawl starting at a URL or .opml path and import OPML docs."""
    try:
        if not SD:
            if messagebox:
                messagebox.showerror("Crawl OPML", "tkinter.simpledialog not available.")
            return
        start = SD.askstring("Crawl OPML (recursive)", "Start URL or local .opml path:", parent=self)
        if not start:
            return
        depth = SD.askinteger("Crawl OPML (recursive)", "Max depth (1–5):",
                              parent=self, minvalue=1, maxvalue=5)
        if not depth:
            return

        # Import adapter lazily
        crawl_and_import = None
        try:
            from modules.opml_crawler_adapter import crawl_and_import as _cai
            crawl_and_import = _cai
        except Exception:
            try:
                from opml_crawler_adapter import crawl_and_import as _cai2
                crawl_and_import = _cai2
            except Exception as e:
                if messagebox:
                    messagebox.showerror("Crawl OPML", f"Adapter not available:\n{e}")
                return

        # Busy cursor
        try:
            self.config(cursor="watch"); self.update_idletasks()
        except Exception:
            pass

        imported_ids = []

        def _import_fn(source: str, xml_text: str):
            try:
                new_id = self.doc_store.add_document(f"OPML: {source}", xml_text)
                imported_ids.append(new_id)
            except Exception as e:
                print("[opml-crawl] import failed:", source, e)

        try:
            crawl_and_import(start, import_fn=_import_fn, max_depth=depth)
        finally:
            try:
                self.config(cursor="")
            except Exception:
                pass

        for rf in ("refresh_index", "_refresh_sidebar"):
            try:
                getattr(self, rf)()
                break
            except Exception:
                pass

        if messagebox:
            if imported_ids:
                messagebox.showinfo("Crawl OPML", f"Imported {len(imported_ids)} OPML doc(s).")
            else:
                messagebox.showinfo("Crawl OPML", "No OPML documents found during crawl.")
    except Exception as e:
        if messagebox:
            messagebox.showerror("Crawl OPML", f"Crawl/import failed:\n{e}\n\n{traceback.format_exc()}")
        else:
            print("[Crawl OPML] failed:", e)
            print(traceback.format_exc())


# -------------------- Install / Wiring --------------------

def attach_opml_extras_plugin(DemoKitGUI_cls):
    """Attach methods to the GUI class (idempotent)."""
    setattr(DemoKitGUI_cls, "_convert_current_to_opml", _convert_current_to_opml)
    setattr(DemoKitGUI_cls, "_batch_convert_selected_to_opml", _batch_convert_selected_to_opml)
    setattr(DemoKitGUI_cls, "_import_url_as_opml", _import_url_as_opml)
    setattr(DemoKitGUI_cls, "_crawl_opml_recursive", _crawl_opml_recursive)
    # legacy alias for callers expecting _crawl_opml
    setattr(DemoKitGUI_cls, "_crawl_opml", _crawl_opml_recursive)


def install_opml_extras_into_app(app):
    """Install menu entries and toolbar buttons onto a running app instance."""
    attach_opml_extras_plugin(app.__class__)

    # Menubar
    try:
        menubar = app.nametowidget(app["menu"]) if app and app["menu"] else None
    except Exception:
        menubar = None
    if menubar is None and tk is not None:
        menubar = tk.Menu(app)
        try:
            app.config(menu=menubar)
        except Exception:
            pass

    if menubar is not None:
        opml_menu = tk.Menu(menubar, tearoff=0)
        opml_menu.add_command(label="Convert → OPML", command=lambda a=app: a._convert_current_to_opml())
        opml_menu.add_command(label="Batch Convert Selected → OPML", command=lambda a=app: a._batch_convert_selected_to_opml())
        opml_menu.add_separator()
        opml_menu.add_command(label="URL → OPML", command=lambda a=app: a._import_url_as_opml())
        opml_menu.add_command(label="Crawl OPML (recursive)…", command=lambda a=app: a._crawl_opml_recursive())
        menubar.add_cascade(label="OPML", menu=opml_menu)

    # Toolbar buttons (optional)
    try:
        tb = getattr(app, "toolbar", None)
        if tb and hasattr(tb, "winfo_exists") and tb.winfo_exists():
            import tkinter.ttk as ttk
            ttk.Button(tb, text="Convert→OPML", command=lambda a=app: a._convert_current_to_opml()).grid(row=0, column=180, padx=(8, 4))
            ttk.Button(tb, text="Batch→OPML", command=lambda a=app: a._batch_convert_selected_to_opml()).grid(row=0, column=181, padx=(0, 4))
    except Exception:
        pass
