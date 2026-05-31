#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FunKit GUI — full replacement

Features in this build:
- Right-hand document pane renders Base64-encoded images inline (PNG/JPEG/GIF/BMP/WEBP)
- Falls back to text rendering with clickable links via hypertext_parser.parse_links
- ASK context menu: sends selected text to CommandProcessor.query_ai and inserts a green link
- Back button navigation stack

Assumptions about existing modules (kept lenient with try/except):
- modules.document_store provides:
    get_document_index() -> list of (doc_id, title_or_preview)
    get_document(doc_id) -> dict or tuple with body/text and optional title
- modules.hypertext_parser provides:
    parse_links(text_widget, content, open_doc_callback)
- commands.CommandProcessor provides:
    query_ai(selected_text, current_doc_id, on_success, on_link_created)

If any of these are missing, we degrade gracefully and keep the app usable.
"""
from __future__ import annotations

import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox

# --- Optional dependencies from your codebase ---------------------------------
try:
    from modules import document_store  # type: ignore
except Exception as e:
    document_store = None  # graceful fallback

try:
    from modules.hypertext_parser import parse_links  # type: ignore
except Exception:
    # Fallback: simple insertion without link parsing
    def parse_links(text_widget: tk.Text, content: str, open_cb: Callable[[int], None]) -> None:  # type: ignore
        text_widget.delete("1.0", "end")
        text_widget.insert("end", content)

try:
    # Base64 image rendering helpers (uploaded as modules/image_render.py)
    from modules.image_render import extract_image_bytes_all, show_images_in_text  # type: ignore
except Exception as e:
    # Minimal inline fallback if helper is unavailable
    extract_image_bytes_all = None  # type: ignore
    show_images_in_text = None  # type: ignore

try:
    from commands import CommandProcessor  # type: ignore
except Exception:
    CommandProcessor = None  # type: ignore


# --- GUI ----------------------------------------------------------------------
class FunKitApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FunKit")
        self.geometry("1100x720")

        self.current_doc_id: Optional[int] = None
        self.history: List[int] = []  # back stack
        self.index_rows: List[Tuple[Any, str]] = []

        self._init_style()
        self._build_layout()
        self._bind_events()

        self.cp = None
        if CommandProcessor is not None:
            try:
                self.cp = CommandProcessor()
            except Exception:
                traceback.print_exc()
                self.cp = None

        self.reload_index()

    # -- UI construction -------------------------------------------------------
    def _init_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

    def _build_layout(self) -> None:
        # Top toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        self.back_btn = ttk.Button(toolbar, text="◀ Back", command=self.go_back)
        self.back_btn.pack(side=tk.LEFT, padx=6, pady=6)

        self.reload_btn = ttk.Button(toolbar, text="Reload Index", command=self.reload_index)
        self.reload_btn.pack(side=tk.LEFT, padx=6, pady=6)

        # Main paned window
        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Left: document list
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        self.tree = ttk.Treeview(left, columns=("id", "title"), show="headings", selectmode="browse")
        self.tree.heading("id", text="ID")
        self.tree.heading("title", text="Title / Preview")
        self.tree.column("id", width=80, anchor=tk.W)
        self.tree.column("title", width=300, anchor=tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        yscroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Right: document pane
        right = ttk.Frame(paned)
        paned.add(right, weight=3)

        self.text = tk.Text(right, wrap="word", undo=True)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        text_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.text.yview)
        self.text.configure(yscrollcommand=text_scroll.set)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Context menu on text widget
        self.text_menu = tk.Menu(self, tearoff=0)
        self.text_menu.add_command(label="ASK (replace with link)", command=self._ask_on_selection)
        self.text_menu.add_separator()
        self.text_menu.add_command(label="Copy", command=lambda: self.text.event_generate("<<Copy>>"))
        self.text_menu.add_command(label="Select All", command=lambda: self.text.event_generate("<<SelectAll>>"))

    def _bind_events(self) -> None:
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.text.bind("<Button-3>", self._show_text_menu)   # Right-click on mac may be <Button-2>
        self.text.bind("<Control-a>", lambda e: (self.text.event_generate("<<SelectAll>>"), "break"))

    # -- Index & navigation ----------------------------------------------------
    def reload_index(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.index_rows.clear()
        try:
            if document_store is None:
                raise RuntimeError("modules.document_store not available")
            rows = document_store.get_document_index()
        except Exception:
            traceback.print_exc()
            rows = []

        # Normalize rows into (id, title)
        norm: List[Tuple[Any, str]] = []
        for r in rows or []:
            if isinstance(r, (list, tuple)):
                if len(r) >= 2:
                    norm.append((r[0], str(r[1])))
                elif len(r) == 1:
                    norm.append((r[0], "(untitled)"))
            elif isinstance(r, dict):
                rid = r.get("id") or r.get("doc_id") or r.get("_id")
                title = r.get("title") or r.get("name") or r.get("preview") or "(untitled)"
                norm.append((rid, str(title)))
            else:
                norm.append((str(r), "(untitled)"))

        self.index_rows = norm
        for rid, title in norm:
            self.tree.insert("", tk.END, values=(rid, title))

    def _on_tree_select(self, event=None) -> None:
        item = self.tree.selection()
        if not item:
            return
        vals = self.tree.item(item[0], "values")
        if not vals:
            return
        doc_id = vals[0]
        self.open_doc_by_id(doc_id)

    def go_back(self) -> None:
        if not self.history:
            return
        if self.current_doc_id is not None:
            # current doc sits on top; pop it first
            top = self.history.pop()
            # if multiple same IDs got stacked, skip duplicates
            while self.history and self.history[-1] == top:
                self.history.pop()
        if self.history:
            prev = self.history.pop()
            self.open_doc_by_id(prev, push_history=False)

    # -- Document loading & rendering -----------------------------------------
    def open_doc_by_id(self, doc_id: Any, push_history: bool = True) -> None:
        try:
            if document_store is None:
                raise RuntimeError("modules.document_store not available")
            doc = document_store.get_document(doc_id)
        except Exception:
            traceback.print_exc()
            messagebox.showerror("Error", f"Failed to load document: {doc_id}")
            return

        # Extract content & title from several possible shapes
        title, content = self._extract_title_content(doc)

        # Update nav history
        if push_history and self.current_doc_id is not None:
            self.history.append(self.current_doc_id)
        self.current_doc_id = doc_id
        self._render_content(content)

        # Update window title with doc id & title
        try:
            self.title(f"FunKit — {doc_id} — {title}")
        except Exception:
            self.title("FunKit")

    def _extract_title_content(self, doc: Any) -> Tuple[str, str]:
        title = "(untitled)"
        content = ""
        if isinstance(doc, dict):
            title = str(doc.get("title") or doc.get("name") or title)
            content = str(
                doc.get("body")
                or doc.get("text")
                or doc.get("content")
                or doc.get("raw")
                or ""
            )
        elif isinstance(doc, (list, tuple)):
            # Common pattern: (id, title, body) or (id, body)
            if len(doc) >= 3:
                title = str(doc[1])
                content = str(doc[2])
            elif len(doc) == 2:
                # decide if 2nd element looks more like title or content
                if isinstance(doc[1], str) and len(doc[1]) < 200:
                    title = str(doc[1])
                    content = ""
                else:
                    content = str(doc[1])
        else:
            content = str(doc)
        return title, content

    def _render_content(self, content: str) -> None:
        # Try inline base64 image rendering if helper is available
        if extract_image_bytes_all and show_images_in_text:
            try:
                blobs = extract_image_bytes_all(content)
            except Exception:
                blobs = []
            if blobs:
                try:
                    ok = show_images_in_text(self.text, blobs)
                    if ok:
                        return  # images rendered; stop here
                except Exception:
                    traceback.print_exc()
                    # fall through to text rendering

        # Otherwise render as rich text with links
        try:
            parse_links(self.text, content, self.open_doc_by_id)
        except Exception:
            traceback.print_exc()
            self.text.delete("1.0", "end")
            self.text.insert("end", content)

    # -- Context menu: ASK -----------------------------------------------------
    def _show_text_menu(self, event) -> None:
        try:
            self.text_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.text_menu.grab_release()

    def _ask_on_selection(self) -> None:
        if self.cp is None:
            messagebox.showwarning("ASK unavailable", "CommandProcessor not available in this build.")
            return
        try:
            sel = self.text.get("sel.first", "sel.last")
        except Exception:
            sel = ""
        if not sel.strip():
            messagebox.showinfo("ASK", "Select some text in the document pane first.")
            return

        cur_id = self.current_doc_id
        if cur_id is None:
            messagebox.showinfo("ASK", "Open a document first.")
            return

        # Call into CommandProcessor with required signature
        def on_success(new_doc_id: Any) -> None:
            try:
                self._insert_green_link_at_selection(new_doc_id, sel)
            except Exception:
                traceback.print_exc()

        def on_link_created(new_doc_id: Any) -> None:
            # For compatibility if your CP calls this separately
            try:
                self._insert_green_link_at_selection(new_doc_id, sel)
            except Exception:
                traceback.print_exc()

        try:
            # Current API (per your note): query_ai(selected_text, current_doc_id, on_success, on_link_created)
            self.cp.query_ai(sel, cur_id, on_success, on_link_created)
        except TypeError:
            # Fallback: older 3-arg signature
            try:
                self.cp.query_ai(sel, cur_id, on_success)
            except Exception:
                traceback.print_exc()
                messagebox.showerror("ASK failed", "Your CommandProcessor.query_ai call failed. See console for details.")
        except Exception:
            traceback.print_exc()
            messagebox.showerror("ASK failed", "Unexpected error. See console for details.")

    def _insert_green_link_at_selection(self, new_doc_id: Any, anchor_text: str) -> None:
        """Replace current selection with a persistent green clickable link.
        Expected link text format (as per your convention):
            "{anchor_text} → [{anchor_text} → ({new_doc_id})]"
        This relies on hypertext_parser.parse_links to turn it into a live link.
        """
        try:
            start = self.text.index("sel.first")
            end = self.text.index("sel.last")
        except Exception:
            return

        link_text = f"{anchor_text} → [{anchor_text} → ({new_doc_id})]"

        # Replace selection
        self.text.delete(start, end)
        self.text.insert(start, link_text)

        # Re-run link parsing on the whole doc (simple approach)
        content_now = self.text.get("1.0", "end-1c")
        try:
            parse_links(self.text, content_now, self.open_doc_by_id)
        except Exception:
            traceback.print_exc()


# --- Entrypoint ---------------------------------------------------------------
if __name__ == "__main__":
    app = FunKitApp()
    app.mainloop()
