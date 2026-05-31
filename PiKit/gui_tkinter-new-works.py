from modules.memory_dialog import open_memory_dialog
import os
import re
import sys
import json
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from pathlib import Path
import xml.etree.ElementTree as ET

# Optional image support (Pillow). If missing, image features will be disabled gracefully.
try:
    from PIL import Image, ImageTk  # type: ignore

    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False


# ---- Optional project modules (guarded so GUI still launches if absent) ----
def _try_import(modpath, name=None, default=None):
    try:
        mod = __import__(modpath, fromlist=["*"])
        return getattr(mod, name, mod) if name else mod
    except Exception:
        return default


hypertext_parser = _try_import("modules.hypertext_parser")
image_generator = _try_import("modules.image_generator")
logger_mod = _try_import("modules.logger")
render_bin_as_text = _try_import("modules.renderer", "render_binary_as_text")
dir_importer = _try_import(
    "modules.directory_import", "import_text_files_from_directory"
)
tree_view_mod = _try_import("modules.TreeView", "open_tree_view")


# Fallbacks
class _NullLogger:
    def info(self, *a, **k):
        print("[INFO]", *a)

    def error(self, *a, **k):
        print("[ERROR]", *a)


Logger = getattr(logger_mod, "Logger", _NullLogger)

SETTINGS_FILE = Path("pikit_settings.json")


class DemoKitGUI(tk.Tk):

    def _build_bottom_toolbar(self, parent):
        """Bottom button row + single search box (no middle toolbar)."""
        from tkinter import ttk, StringVar

        bar = ttk.Frame(parent)
        bar.grid(row=2, column=0, sticky="ew", pady=(6, 4))
        for c in range(8):
            bar.grid_columnconfigure(c, weight=1)
            ttk.Button(bar, text="TREE", command=self.on_tree_button).grid(
                row=0, column=0, sticky="ew", padx=3
            )
            ttk.Button(bar, text="OPEN OPML", command=self._open_opml_from_main).grid(
                row=0, column=1, sticky="ew", padx=3
            )
            ttk.Button(bar, text="ASK", command=self._on_ask).grid(
                row=0, column=2, sticky="ew", padx=3
            )
            ttk.Button(bar, text="BACK", command=self._go_back).grid(
                row=0, column=3, sticky="ew", padx=3
            )
            ttk.Button(bar, text="DIR IMPORT", command=self._import_directory).grid(
                row=0, column=4, sticky="ew", padx=3
            )
            ttk.Button(bar, text="EXPORT", command=self._export_doc).grid(
                row=0, column=5, sticky="ew", padx=3
            )
            ttk.Label(bar, text="Search:").grid(
                row=0, column=6, sticky="e", padx=(12, 4)
            )
            self._search_var = StringVar()
            entry = ttk.Entry(bar, textvariable=self._search_var)
            entry.grid(row=0, column=7, sticky="ew", padx=(0, 3))
            entry.bind("<Return>", lambda e: self.filter_index(self._search_var.get()))
            self._search_entry = entry
            return bar

    def _open_memory_dialog(self):
        try:
            open_memory_dialog(self)
        except Exception as e:
            try:
                from tkinter import messagebox

                messagebox.showerror("Memory", f"Could not open memory dialog:\n{e}")
            except Exception:
                print("[Memory] Could not open:", e)

    """PiKit GUI with OPML rendering, search, and basic import/export utilities."""

    SIDEBAR_WIDTH = 320

    def __init__(self, doc_store, processor):
        super().__init__()
        self.root = self  # keep compatibility with code that expects self.root
        self.doc_store = doc_store
        self.processor = processor
        self.logger = getattr(processor, "logger", Logger())

        self.current_doc_id = None
        self.history = []
        self._suppress_sidebar_select = False

        # Settings
        self.settings = self._load_settings()
        self.opml_expand_depth = int(self.settings.get("opml_expand_depth", 2))

        self.title("Engelbart Journal — PiKit")
        geom = self.settings.get("geometry")
        try:
            self.geometry(geom if geom else "1200x800")
        except Exception:
            self.geometry("1200x800")

        # Grid
        self.columnconfigure(0, minsize=self.SIDEBAR_WIDTH, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # UI
        self._build_sidebar()
        self._build_main_pane()
        self._build_context_menu()
        self._build_menus()

        # Initial data
        self.refresh_index()

        # Close protocol
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- Settings ----------------
    def _load_settings(self) -> dict:
        defaults = {
            "geometry": None,
            "opml_expand_depth": 2,
            "sidebar_width": self.SIDEBAR_WIDTH,
            "recent_docs": [],
            "memory": {},
            "theme": "light",
        }
        try:
            if SETTINGS_FILE.exists():
                with SETTINGS_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    out = defaults.copy()
                    out.update(data)
                    return out
        except Exception as e:
            print("[settings] load failed:", e)
        return defaults

    def _save_settings(self) -> None:
        try:
            data = dict(self.settings or {})
            data["geometry"] = self.geometry()
            data["opml_expand_depth"] = int(
                getattr(self, "opml_expand_depth", data.get("opml_expand_depth", 2))
            )
            data["sidebar_width"] = getattr(
                self, "SIDEBAR_WIDTH", data.get("sidebar_width", 320)
            )
            with SETTINGS_FILE.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print("[settings] save failed:", e)

    def _on_close(self):
        try:
            self._save_settings()
        except Exception:
            pass
        self.destroy()

    # ---------------- Menus & Toolbar ----------------
    def _build_menus(self):
        menubar = tk.Menu(self)

        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Import…", command=self._import_doc)
        filemenu.add_command(label="Export Current…", command=self._export_doc)
        filemenu.add_separator()
        filemenu.add_command(label="Memory…", command=self._open_memory_dialog)
        filemenu.add_command(label="Quit", command=self._on_close)
        menubar.add_cascade(label="File", menu=filemenu)

        viewmenu = tk.Menu(menubar, tearoff=0)
        viewmenu.add_command(
            label="Document Tree", command=self.on_tree_button, accelerator="Ctrl+T"
        )
        viewmenu.add_command(
            label="Set OPML Expand Depth…", command=self._set_opml_expand_depth
        )
        menubar.add_cascade(label="View", menu=viewmenu)

        self.config(menu=menubar)
        self.bind("<Control-m>", lambda e: (self._open_memory_dialog(), "break"))
        self.bind("<Alt-Left>", lambda e: (self._go_back(), "break"))
        self.bind("<Control-t>", lambda e: self.on_tree_button())

    def _build_sidebar(self):
        frame = tk.Frame(self)
        frame.grid(row=0, column=0, sticky="nswe")
        self.sidebar = ttk.Treeview(
            frame, columns=("ID", "Title", "Description"), show="headings"
        )
        for col, w in (("ID", 70), ("Title", 180), ("Description", 220)):
            self.sidebar.heading(col, text=col)
            self.sidebar.column(
                col, width=w, anchor="w", stretch=(col == "Description")
            )
        self.sidebar.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Scrollbar(frame, orient="vertical", command=self.sidebar.yview).pack(
            side=tk.RIGHT, fill=tk.Y
        )
        self.sidebar.bind("<<TreeviewSelect>>", self._on_select)

    def _build_main_pane(self):

        # Remove any center/middle toolbar remnants
        for attr in ("mid_panel", "toolbar"):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.destroy()
                except Exception:
                    pass
                setattr(self, attr, None)

        pane = tk.Frame(self)
        pane.grid(row=0, column=1, sticky="nswe", padx=4, pady=4)
        pane.rowconfigure(0, weight=3)
        pane.rowconfigure(1, weight=0)
        pane.rowconfigure(2, weight=0)
        pane.columnconfigure(0, weight=1)

        if not hasattr(self, "text") or not isinstance(self.text, tk.Text):
            self.text = tk.Text(pane, wrap="word")
        self.text.grid(row=0, column=0, sticky="nswe")
        self.text.tag_configure("link", foreground="green", underline=True)
        self.text.bind(
            "<Button-3>", getattr(self, "_show_context_menu", lambda e: None)
        )

        if not hasattr(self, "img_label"):
            self.img_label = tk.Label(pane)
        self.img_label.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        try:
            self.img_label.bind(
                "<Button-1>", lambda e: getattr(self, "toggle_image_size")()
            )
        except Exception:
            pass
        # keep hidden until used
        try:
            self.img_label.grid_remove()
        except Exception:
            pass

        self._build_bottom_toolbar(pane)

    def _build_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Memory…", command=self._open_memory_dialog)
        self.context_menu.add_command(label="Delete", command=self._on_delete_clicked)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Import…", command=self._import_doc)
        self.context_menu.add_command(label="Export…", command=self._export_doc)

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    # ---------------- Search ----------------
    def _install_search_ui(self):

        self._search_var = tk.StringVar()
        self._search_after_id = None

        # place the search row under the buttons
        existing_rows = [
        int(w.grid_info().get("row", 0)) for w in self.toolbar.grid_slaves()
        ]
        next_row = (max(existing_rows) + 1) if existing_rows else 0

        ttk.Label(self.toolbar, text="Search:").grid(
            row=next_row, column=0, padx=(2, 2), pady=(6, 2), sticky="w"
        )
        self._search_entry = ttk.Entry(
            self.toolbar, textvariable=self._search_var, width=22
        )
        self._search_entry.grid(
            row=next_row, column=1, padx=(0, 6), pady=(6, 2), sticky="ew"
        )
        # Do NOT let the entry stretch the toolbar width
        # self.toolbar.grid_columnconfigure(1, weight=0)

        self._search_entry.insert(0, "title or text…")
        self._search_entry.bind(
            "<FocusIn>", lambda e: self._search_entry.delete(0, "end")
        )
        self._search_entry.bind(
            "<Return>", lambda e: self.filter_index(self._search_var.get())
        )

    def _clear_placeholder(self):
        if self._search_entry.get() == "title or text…":
            self._search_entry.delete(0, "end")

    def _on_search_changed(self):
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(200, self._apply_search)

    def _apply_search(self):
        q = (self._search_var.get() or "").strip()
        if not q or q == "title or text…":
            self.refresh_index()
        else:
            self.filter_index(q)

    # ---------------- Sidebar / Index ----------------
    def refresh_index(self):
        """Reload the flat document list into the index pane."""
        self.sidebar.delete(*self.sidebar.get_children())
        try:
            rows = (
                self.doc_store.get_document_index()
            )  # expected: iterable of dicts {id,title,description}
        except Exception:
            rows = []
        for row in rows:
            if isinstance(row, dict):
                doc_id = row.get("id")
                title = row.get("title", "")
                desc = row.get("description", "")
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                doc_id, title = row[0], row[1]
                desc = row[2] if len(row) > 2 else ""
            else:
                continue
            self.sidebar.insert("", "end", values=(doc_id, title, desc))

    def filter_index(self, query: str):
        """Filter by title/body. Requires doc_store.search_docs; falls back to naive filtering."""
        self.sidebar.delete(*self.sidebar.get_children())
        try:
            matches = self.doc_store.search_docs(
                query
            )  # expected rows: (id, title) or dicts
        except Exception:
            ql = query.lower()
            base = getattr(self.doc_store, "get_document_index", lambda: [])()
            matches = [
                (d["id"], d.get("title", ""))
                for d in base
                if isinstance(d, dict)
                and (d.get("title", "") + d.get("description", "")).lower().find(ql)
                >= 0
            ]
        for row in matches:
            if isinstance(row, dict):
                doc_id, title = row.get("id"), row.get("title", "")
            elif isinstance(row, (list, tuple)):
                doc_id, title = row[0], row[1] if len(row) > 1 else ""
            else:
                continue
            self.sidebar.insert("", "end", values=(doc_id, title, ""))

    def _on_select(self, event):
        if self._suppress_sidebar_select:
            return
        sel = self.sidebar.selection()
        if not sel:
            return
        vals = self.sidebar.item(sel[0], "values") or []
        if not vals:
            return
        try:
            doc_id = int(vals[0])
        except Exception:
            return
        if self.current_doc_id is not None:
            self.history.append(self.current_doc_id)
        self.current_doc_id = doc_id
        self._open_doc_id(doc_id)

    def _select_tree_item_for_doc(self, doc_id: int):
        tv = self.sidebar
        found = None
        for iid in tv.get_children(""):
            vals = tv.item(iid, "values") or ()
            if vals and str(vals[0]) == str(doc_id):
                found = iid
                break
        if found:
            prev = self._suppress_sidebar_select
            try:
                self._suppress_sidebar_select = True
                tv.selection_set(found)
                tv.focus(found)
                tv.see(found)
            finally:
                self.after_idle(lambda: setattr(self, "_suppress_sidebar_select", prev))

    # ---------------- TreeView wiring ----------------
    def on_tree_button(self):
        """Open a TreeView window rooted at current doc (if available)."""
        if not tree_view_mod:
            messagebox.showwarning("TreeView", "TreeView module not available.")
            return

        # Simple adapter based on green links "(doc:ID)"
        class _Repo:
            def __init__(self, ds):
                self.ds = ds

            def get_doc(self, doc_id):
                d = self.ds.get_document(doc_id)
                if not d:
                    return None
                if isinstance(d, dict):
                    return type(
                        "Node",
                        (object,),
                        {
                            "id": d.get("id"),
                            "title": d.get("title") or "(untitled)",
                            "parent_id": None,
                        },
                    )()
                return type(
                    "Node",
                    (object,),
                    {
                        "id": d[0],
                        "title": (d[1] if len(d) > 1 else "(untitled)"),
                        "parent_id": None,
                    },
                )()

            def get_children(self, parent_id):
                if parent_id is None:
                    ids = [r["id"] for r in self.ds.get_document_index()]
                    refd = set()
                    for r in self.ds.get_document_index():
                        d = self.ds.get_document(r["id"])
                        body = (
                            d.get("body")
                            if isinstance(d, dict)
                            else (d[2] if len(d) > 2 else "")
                        )
                        if not isinstance(body, str):
                            continue
                        refd.update(int(m) for m in re.findall(r"\(doc:(\d+)\)", body))
                    roots = [self.get_doc(i) for i in ids if i not in refd] or [
                        self.get_doc(i) for i in ids
                    ]
                    return [n for n in roots if n]
                d = self.ds.get_document(parent_id)
                body = (
                    d.get("body")
                    if isinstance(d, dict)
                    else (d[2] if len(d) > 2 else "")
                )
                ids = (
                    [int(m) for m in re.findall(r"\(doc:(\d+)\)", body)]
                    if isinstance(body, str)
                    else []
                )
                return [self.get_doc(i) for i in ids if self.get_doc(i)]

        win = tree_view_mod(
            self,
            repo=_Repo(self.doc_store),
            on_open_doc=self._open_doc_id,
            root_doc_id=self.current_doc_id,
        )
        # Expand a bit if supported
        try:
            if hasattr(win, "_expand_to_depth"):
                win._expand_to_depth(self.opml_expand_depth)
        except Exception:
            pass

    # ---------------- Import/Export ----------------
    def _import_doc(self):
        path = filedialog.askopenfilename(
            title="Import",
            filetypes=[
                ("Text", "*.txt *.md *.html *.opml *.xml"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            data = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            messagebox.showerror("Import", f"Failed to read file:\n{e}")
            return
        title = Path(path).name
        try:
            nid = self.doc_store.add_document(title, data)
        except Exception as e:
            messagebox.showerror("Import", f"Failed to add to DB:\n{e}")
            return
        self.refresh_index()
        self._open_doc_id(nid)
        self._select_tree_item_for_doc(nid)

    def _export_doc(self):
        if self.current_doc_id is None:
            messagebox.showwarning("Export", "No document selected.")
            return
        doc = self.doc_store.get_document(self.current_doc_id)
        if not doc:
            messagebox.showerror("Export", "Document not found.")
            return
        if isinstance(doc, dict):
            title = doc.get("title") or "Document"
            body = doc.get("body") or ""
            ctype = (doc.get("content_type") or "").lower()
        else:
            title = doc[1] if len(doc) > 1 else "Document"
            body = doc[2] if len(doc) > 2 else ""
            ctype = ""
        safe = (
            "".join(c if (c.isalnum() or c in "._- ") else "_" for c in title).strip()
            or "Document"
        )
        ext = ".opml" if (isinstance(body, str) and "<opml" in body.lower()) else ".txt"
        path = filedialog.asksaveasfilename(
            title="Export Document", defaultextension=ext, initialfile=f"{safe}{ext}"
        )
        if not path:
            return
        try:
            if isinstance(body, (bytes, bytearray)):
                Path(path).write_bytes(bytes(body))
            else:
                Path(path).write_text(body, encoding="utf-8", newline="\n")
            messagebox.showinfo("Export", f"Saved:\n{path}")
        except Exception as e:
            messagebox.showerror("Export", f"Could not save:\n{e}")

    def _import_directory(self):
        if not dir_importer:
            messagebox.showwarning(
                "Directory Import", "Directory import module not available."
            )
            return
        dir_path = filedialog.askdirectory(title="Select Folder to Import")
        if not dir_path:
            return
        try:
            imported, skipped = dir_importer(dir_path, self.doc_store)
        except Exception as e:
            messagebox.showerror("Directory Import", f"Failed:\n{e}")
            return
        messagebox.showinfo(
            "Directory Import", f"Imported {imported} file(s), skipped {skipped}."
        )
        self.refresh_index()

    # ---------------- Open OPML into DB ----------------
    def _open_opml_from_main(self):
        path = filedialog.askopenfilename(
            title="Open OPML/XML",
            filetypes=[("OPML / XML", "*.opml *.xml"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            messagebox.showerror("Open OPML", f"Failed to read file:\n{e}")
            return
        title = Path(path).stem
        try:
            new_id = self.doc_store.add_document(title, content)
        except Exception as e:
            messagebox.showerror("Open OPML", f"Failed to import OPML to DB:\n{e}")
            return
        self.refresh_index()
        self._open_doc_id(new_id)
        self._select_tree_item_for_doc(new_id)

    # ---------------- Rendering ----------------
    def _open_doc_id(self, doc_id: int):
        doc = self.doc_store.get_document(doc_id)
        if not doc:
            return
        self.current_doc_id = doc_id
        self._render_document(doc)

    def _render_document(self, doc):
        """Render text, OPML-as-tree, or local image bytes."""
        # normalize tuple/dict
        if isinstance(doc, dict):
            body = doc.get("body")
            ctype = (doc.get("content_type") or "").lower()
            title = doc.get("title") or ""
        else:
            body = doc[2] if len(doc) > 2 else ""
            ctype = ""
            title = doc[1] if len(doc) > 1 else ""

        # OPML detection
        if isinstance(body, str) and "<opml" in body.lower():
            self._render_opml_from_string(body)
            return

        # hide OPML tree if showing
        self._hide_opml()

        # IMAGE (local bytes only)
        if isinstance(body, (bytes, bytearray)) and _HAVE_PIL:
            self._show_image_bytes(body, title, ctype)
            return

        # Plain text / HTML
        self.text.delete("1.0", tk.END)
        if isinstance(body, (bytes, bytearray)):
            try:
                body = body.decode("utf-8")
            except Exception:
                body = body.decode("latin-1", errors="replace")
        self.text.insert("1.0", body or "")
        # link parsing if module exists
        try:
            if hypertext_parser:
                hypertext_parser.parse_links(
                    self.text, body or "", self._on_green_link_click
                )
        except Exception:
            pass

    def _on_green_link_click(self, doc_id):
        if self.current_doc_id is not None:
            self.history.append(self.current_doc_id)
        self._open_doc_id(int(doc_id))

    # ---- OPML widgets ----
    def _ensure_opml_widgets(self):
        if hasattr(self, "_opml_frame") and self._opml_frame.winfo_exists():
            return
        pane = self.text.master
        self._opml_frame = tk.Frame(pane)
        self._opml_frame.grid(row=0, column=0, sticky="nswe")
        tb = tk.Frame(self._opml_frame)
        tb.pack(side=tk.TOP, fill=tk.X)
        self._opml_show_nums = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            tb,
            text="Show Numbers",
            variable=self._opml_show_nums,
            command=self._opml_update_numbering,
        ).pack(side=tk.LEFT, padx=6)
        self._opml_tree = ttk.Treeview(
            self._opml_frame, columns=("num",), show="tree headings"
        )
        self._opml_tree.heading("num", text="No.")
        self._opml_tree.column("num", width=90, minwidth=60, stretch=False, anchor="e")
        vsb = ttk.Scrollbar(
            self._opml_frame, orient="vertical", command=self._opml_tree.yview
        )
        hsb = ttk.Scrollbar(
            self._opml_frame, orient="horizontal", command=self._opml_tree.xview
        )
        self._opml_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._opml_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

    def _show_opml(self):
        self._ensure_opml_widgets()
        if self.text.winfo_manager():
            self.text.grid_remove()
        self._opml_frame.lift()
        self._opml_frame.grid()

    def _hide_opml(self):
        if hasattr(self, "_opml_frame") and self._opml_frame.winfo_exists():
            self._opml_frame.grid_remove()
        if not self.text.winfo_manager():
            self.text.grid(row=0, column=0, sticky="nswe")

    def _render_opml_from_string(self, s: str):
        try:
            s = s.decode("utf-8") if isinstance(s, (bytes, bytearray)) else s
            s = (s or "").lstrip("\ufeff\r\n\t ")
            root = ET.fromstring(s)
        except Exception as e:
            print("[OPML] parse failed:", e)
            # fallback: just show text
            self._hide_opml()
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", s or "")
            return
        if (root.tag or "").lower() != "opml":
            self._hide_opml()
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", s or "")
            return

        self._show_opml()
        for iid in self._opml_tree.get_children(""):
            self._opml_tree.delete(iid)

        body = None
        for child in root:
            if child.tag.lower().endswith("body"):
                body = child
                break
        outlines = body.findall("outline") if body is not None else list(root)

        def insert_elem(parent_iid, elem):
            text = (
                elem.attrib.get("text")
                or elem.attrib.get("title")
                or (elem.text.strip() if elem.text else "")
                or "[No Text]"
            )
            iid = self._opml_tree.insert(parent_iid, "end", text=text)
            for c in elem:
                tag = (c.tag or "").lower()
                if tag.endswith("outline") or tag in {"outline", "node", "item"}:
                    insert_elem(iid, c)

        for e in outlines:
            tag = (e.tag or "").lower()
            if tag.endswith("outline") or tag in {"outline", "node", "item"}:
                insert_elem("", e)

        self._opml_expand_to_depth_in_pane(self.opml_expand_depth)
        self._opml_update_numbering()

    def _opml_expand_to_depth_in_pane(self, depth: int):
        if not hasattr(self, "_opml_tree"):
            return

        def walk(iid, d):
            if d >= depth:
                return
            self._opml_tree.item(iid, open=True)
            for c in self._opml_tree.get_children(iid):
                walk(c, d + 1)

        for top in self._opml_tree.get_children(""):
            walk(top, 0)

    def _opml_update_numbering(self):
        if not hasattr(self, "_opml_tree"):
            return
        try:
            show = bool(self._opml_show_nums.get())
        except Exception:
            show = True
        if not show:
            self._opml_tree.column("num", width=0, minwidth=0, stretch=False)
            for c in self._opml_tree.get_children(""):
                self._opml_tree.set(c, "num", "")
            return
        self._opml_tree.column("num", width=90, minwidth=60, stretch=False, anchor="e")

        def renumber(iid="", prefix=None):
            if prefix is None:
                prefix = []
            kids = self._opml_tree.get_children(iid)
            for idx, c in enumerate(kids, start=1):
                parts = prefix + [idx]
                self._opml_tree.set(c, "num", ".".join(str(n) for n in parts))
                renumber(c, parts)

        renumber("")

    # ---------------- Image helpers ----------------
    def _show_image_bytes(self, data: bytes, title: str, ctype: str):
        if not _HAVE_PIL:
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", "[Image support unavailable]")
            return
        from io import BytesIO

        try:
            pil_img = Image.open(BytesIO(bytes(data)))
            thumb = pil_img.copy()
            thumb.thumbnail((900, 500))
            tk_img = ImageTk.PhotoImage(thumb)
            self.img_label.configure(image=tk_img)
            self.img_label.image = tk_img
            self.img_label.grid(row=0, column=0, sticky="ew", pady=(6, 0))
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", f"{title or 'Image'} ({ctype or 'image'})\n")
        except Exception as e:
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", f"[image decode failed: {e}]")

    # ---------------- Delete ----------------
    def _on_delete_clicked(self):
        sel = self.sidebar.selection()
        if not sel:
            messagebox.showwarning("Delete", "No document selected.")
            return
        vals = self.sidebar.item(sel[0], "values") or []
        if not vals:
            return
        try:
            nid = int(vals[0])
        except Exception:
            return
        if not messagebox.askyesno("Confirm Delete", f"Delete document ID {nid}?"):
            return
        try:
            self.doc_store.delete_document(nid)
        except Exception as e:
            messagebox.showerror("Delete", f"Failed to delete: {e}")
            return
        self.refresh_index()
        self.text.delete("1.0", tk.END)
        if hasattr(self, "_opml_frame") and self._opml_frame.winfo_exists():
            self._opml_frame.grid_remove()
        if hasattr(self.img_label, "image"):
            self.img_label.configure(image="")
            self.img_label.image = None
        self.current_doc_id = None
        messagebox.showinfo("Deleted", f"Document {nid} deleted.")

    # ---------------- Settings helpers ----------------
    def _set_opml_expand_depth(self):
        try:
            val = simpledialog.askinteger(
                "OPML Expand Depth",
                "How deep to expand OPML trees (1–6)?",
                parent=self,
                minvalue=1,
                maxvalue=6,
                initialvalue=self.opml_expand_depth,
            )
            if val:
                self.opml_expand_depth = int(val)
                self._save_settings()
                # update current OPML pane if visible
                try:
                    self._opml_expand_to_depth_in_pane(self.opml_expand_depth)
                    self._opml_update_numbering()
                except Exception:
                    pass
        except Exception:
            pass

    def _on_ask(self):

        prefix = simpledialog.askstring(
            "ASK prefix", "Enter prefix:", initialvalue="Please expand on this:"
        )
        if prefix is None:
            return
        try:
            sel = self.text.get("sel.first", "sel.last")
        except Exception:
            sel = ""
            if not sel.strip():
                messagebox.showinfo("ASK", "Select some text to ask about.")
                return

        current_id = getattr(self, "current_doc_id", None)
        if current_id is None:
            messagebox.showerror("ASK", "No active document is loaded.")
            return

        self.processor.query_ai(
            selected_text=sel,
            current_doc_id=current_id,
            on_success=lambda new_id: messagebox.showinfo(
                "ASK", f"Created new document {new_id}", prefix=prefix
            ),
            on_link_created=lambda _t: self.render_document(current_id),
            prefix="Please expand on this:",
        )

    def _go_back(self):
        if not getattr(self, "history", None):
            messagebox.showinfo("BACK", "No history.")
        prev = self.history.pop() 
        self.current_doc_id = prev
        doc = self.doc_store.get_document(prev)
        if doc:
            self._render_document(doc)
        else:
            messagebox.showerror("BACK", f"Document {prev} not found.")
        if self.current_doc_id is not None:
            self.history.append(self.current_doc_id)
        if self.current_doc_id is not None:
           self._open_doc_id(doc_id)

    def _on_search_clicked(self):
        q = simpledialog.askstring("Search", "Enter query:")
        if q:
            self.filter_index(q)
