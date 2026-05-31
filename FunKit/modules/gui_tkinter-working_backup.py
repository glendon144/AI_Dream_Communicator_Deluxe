import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from pathlib import Path
from PIL import ImageTk, Image
import subprocess
import sys
import json
import re
import xml.etree.ElementTree as ET

# === Tri-model integration imports ===
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox
from modules.tri_pipeline import run_tri_pipeline
from modules.ai_memory import get_memory, set_memory


# FunKit modules
from modules import hypertext_parser, image_generator, document_store
from modules.renderer import render_binary_as_text
from modules.logger import Logger
from modules.directory_import import import_text_files_from_directory
from modules.TreeView import open_tree_view

SETTINGS_FILE = Path("funkit_settings.json")


class DemoKitGUI(tk.Tk):
    """FunKit / DemoKit GUI with OPML auto-rendering in the document pane, TreeView integration, and utilities."""

    SIDEBAR_WIDTH = 320

    def __init__(self, doc_store, processor):
        super().__init__()
        self.doc_store = doc_store
        self.processor = processor
        self.logger: Logger = getattr(processor, "logger", Logger())
        self.current_doc_id: int | None = None
        self.history: list[int] = []
# idempotent;  safe to call each startup
        # image state
        self._last_pil_img: Image.Image | None = None
        self._last_tk_img: ImageTk.PhotoImage | None = None
        self._image_enlarged: bool = False

        # ---- Settings ----
        self.settings = self._load_settings()
        self.opml_expand_depth: int = int(self.settings.get("opml_expand_depth", 2))

        self.title("Engelbart Journal – DemoKit")
        self.geometry("1200x800")
        self.columnconfigure(0, minsize=self.SIDEBAR_WIDTH, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_pane()
        self._build_context_menu()

        # --- Menubar ---
        menubar = tk.Menu(self)
        # File menu
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Import", command=self._import_doc)
        filemenu.add_command(label="Export Current", command=self._export_doc)
        filemenu.add_separator()
        filemenu.add_command(label="Export to Intraweb", command=self.export_and_launch_server)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)

        # View menu (adds TreeView entry + shortcut + depth)
        viewmenu = tk.Menu(menubar, tearoff=0)
        viewmenu.add_command(label="Document Tree\tCtrl+T", command=self.on_tree_button)
        viewmenu.add_separator()
        viewmenu.add_command(label="Set OPML Expand Depth…", command=self._set_opml_expand_depth)
        menubar.add_cascade(label="View", menu=viewmenu)

        self.config(menu=menubar)
        # AI menu
        ai_menu = tk.Menu(menubar, tearoff=0)
        ai_menu.add_command(label="ASK (Tri)", command=self.ask_tri_action, accelerator="Ctrl+Shift+A")
        menubar.add_cascade(label="AI", menu=ai_menu)

        # Keyboard shortcut
        self.bind("<Control-t>", lambda e: self.on_tree_button())

        self.bind_all("<Control-Shift-A>", lambda e: self.ask_tri_action())

        self._refresh_sidebar()
        # Thread pool (keeps UI responsive during API calls)
        self.executor = getattr(self, "executor", ThreadPoolExecutor(max_workers=2))

    # ---------------- Settings ----------------

    def _load_settings(self) -> dict:
        try:
            if SETTINGS_FILE.exists():
                return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_settings(self):
        try:
            SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except Exception as e:
            print("[WARN] Could not save settings:", e)

    def _set_opml_expand_depth(self):
        val = simpledialog.askinteger(
            "OPML Expand Depth",
            "Expand OPML to depth (0=root, 1=children, 2=grandchildren…):",
            initialvalue=self.opml_expand_depth,
            minvalue=0,
            maxvalue=99,
        )
        if val is None:
            return
        self.opml_expand_depth = int(val)
        self.settings["opml_expand_depth"] = self.opml_expand_depth
        self._save_settings()
        # If a Tree window with OPML loaded is open, apply immediately
        win = getattr(self, "tree_win", None)
        if win and win.winfo_exists():
            self._apply_opml_expand_depth()

    # ---------------- Sidebar ----------------

    def _build_sidebar(self):
        frame = tk.Frame(self)
        frame.grid(row=0, column=0, sticky="nswe")
        self.sidebar = ttk.Treeview(frame, columns=("ID", "Title", "Description"), show="headings")
        for col, w in (("ID", 60), ("Title", 120), ("Description", 160)):
            self.sidebar.heading(col, text=col)
            self.sidebar.column(col, width=w, anchor="w", stretch=(col == "Description"))
        self.sidebar.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Scrollbar(frame, orient="vertical", command=self.sidebar.yview).pack(side=tk.RIGHT, fill=tk.Y)
        self.sidebar.bind("<<TreeviewSelect>>", self._on_select)
        self.sidebar.bind("<Delete>", lambda e: self._on_delete_clicked())

    def _refresh_sidebar(self):
        self.sidebar.delete(*self.sidebar.get_children())
        for doc in self.doc_store.get_document_index():
            self.sidebar.insert("", "end", values=(doc["id"], doc["title"], doc["description"]))

    def _on_select(self, event):
        sel = self.sidebar.selection()
        if not sel:
            return
        item = self.sidebar.item(sel[0])
        try:
            nid = int(item["values"][0])
        except (ValueError, TypeError):
            return
        if self.current_doc_id is not None:
            self.history.append(self.current_doc_id)
        self.current_doc_id = nid
        doc = self.doc_store.get_document(nid)
        if doc:
            self._render_document(doc)

    # ---------------- Main Pane ----------------

    def _build_main_pane(self):
        pane = tk.Frame(self)
        pane.grid(row=0, column=1, sticky="nswe", padx=4, pady=4)
        pane.rowconfigure(0, weight=3)
        pane.rowconfigure(1, weight=1)
        pane.columnconfigure(0, weight=1)

        self.text = tk.Text(pane, wrap="word")
        self.text.grid(row=0, column=0, sticky="nswe")
        self.text.tag_configure("link", foreground="green", underline=True)
        self.text.bind("<Button-3>", self._show_context_menu)
        self.text.bind("<Delete>", lambda e: self._on_delete_clicked())

        self.img_label = tk.Label(pane)
        self.img_label.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.img_label.bind("<Button-1>", lambda e: self._toggle_image())

        btns = tk.Frame(pane)
        btns.grid(row=2, column=0, sticky="we", pady=(6, 0))
        self.toolbar = btns   # <- expose the toolbar so plugins can attach buttons

        acts = [
            ("TREE", self.on_tree_button),
            ("OPEN OPML", self._open_opml_from_main),
            ("ASK", self._handle_ask),
            ("ASK (Tri)", self.ask_tri_action),
            ("BACK", self._go_back),
            ("DELETE", self._on_delete_clicked),
            ("IMAGE", self._handle_image),
            ("FLASK", self.export_and_launch_server),
            ("DIR IMPORT", self._import_directory),
            ("SAVE AS TEXT", self._save_binary_as_text),
        ]
        for i, (lbl, cmd) in enumerate(acts):
            ttk.Button(btns, text=lbl, command=cmd).grid(row=0, column=i, sticky="we", padx=(0, 4))

    # ---------------- Context Menu ----------------

    def _build_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="ASK", command=self._handle_ask)
        self.context_menu.add_command(label="ASK (Tri)", command=self.ask_tri_action)
        self.context_menu.add_command(label="Delete", command=self._on_delete_clicked)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Import", command=self._import_doc)
        self.context_menu.add_command(label="Export", command=self._export_doc)
        self.context_menu.add_command(label="Save Binary As Text", command=self._save_binary_as_text)

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    # ---------------- ASK / BACK ----------------

    def _handle_ask(self):
        try:
            start = self.text.index(tk.SEL_FIRST)
            end = self.text.index(tk.SEL_LAST)
            selected_text = self.text.get(start, end)
        except tk.TclError:
            messagebox.showwarning("ASK", "Please select some text first.")
            return

        cid = self.current_doc_id

        def on_success(nid):
            messagebox.showinfo("ASK", f"Created new document {nid}.")
            self._refresh_sidebar()
            # replace selection with link
            self.text.delete(start, end)
            link_md = f"[{selected_text}](doc:{nid})"
            self.text.insert(start, link_md)
            full = self.text.get("1.0", tk.END)
            doc = self.doc_store.get_document(nid)
            if isinstance(doc["body"], bytes):
                self.text.insert(tk.END, "[binary document]")
                return
            hypertext_parser.parse_links(self.text, full, self._on_link_click)

        prefix = simpledialog.askstring("Prefix", "Optional prefix:", initialvalue="Please expand:")
        self.processor.query_ai(
            selected_text, cid, on_success, lambda *_: None, prefix=prefix, sel_start=None, sel_end=None
        )

    def _go_back(self):
        if not self.history:
            messagebox.showinfo("BACK", "No history.")
            return
        prev = self.history.pop()
        self.current_doc_id = prev
        doc = self.doc_store.get_document(prev)
        if doc:
            self._render_document(doc)
        else:
            messagebox.showerror("BACK", f"Document {prev} not found.")

    # ---------------- TreeView wiring ----------------

    def on_tree_button(self):
        """Open the TreeView window using the current document as the root (if any)."""

        class _DocStoreRepo:
            """Adapter that derives parent→children from green links like (doc:123)."""

            def __init__(self, ds):
                self.ds = ds
                self._roots_cache = None

            def _mk_node(self, d):
                if not d:
                    return None
                if isinstance(d, dict):
                    return type(
                        "DocNodeShim",
                        (object,),
                        {
                            "id": d.get("id"),
                            "title": d.get("title") or "(untitled)",
                            "parent_id": d.get("parent_id"),
                        },
                    )()
                did = d[0] if len(d) > 0 else None
                title = d[1] if len(d) > 1 else ""
                return type("DocNodeShim", (object,), {"id": did, "title": title or "(untitled)", "parent_id": None})()

            def get_doc(self, doc_id: int):
                return self._mk_node(self.ds.get_document(doc_id))

            def _body(self, doc):
                return doc["body"] if isinstance(doc, dict) else (doc[2] if len(doc) > 2 else "")

            def _children_from_links(self, parent_id):
                d = self.ds.get_document(parent_id)
                if not d:
                    return []
                body = self._body(d)
                if isinstance(body, (bytes, bytearray)):
                    return []
                ids = [int(m) for m in re.findall(r"\(doc:(\d+)\)", body)]
                out = []
                for cid in ids:
                    nd = self.ds.get_document(cid)
                    if nd:
                        out.append(self._mk_node(nd))
                out.sort(key=lambda n: n.id)
                return out

            def get_children(self, parent_id):
                # No parent_id column in the DB, so derive from green-link references
                if parent_id is None:
                    if self._roots_cache is None:
                        all_ids = [row["id"] for row in self.ds.get_document_index()]
                        referenced = set()
                        for row in self.ds.get_document_index():
                            d = self.ds.get_document(row["id"])
                            body = self._body(d)
                            if isinstance(body, (bytes, bytearray)):
                                continue
                            referenced.update(int(m) for m in re.findall(r"\(doc:(\d+)\)", body))
                        # roots = docs never referenced by any other doc
                        roots = [self._mk_node(self.ds.get_document(i)) for i in all_ids if i not in referenced]
                        if not roots:  # fallback: show all if everything is referenced
                            roots = [self._mk_node(self.ds.get_document(i)) for i in all_ids]
                        self._roots_cache = [n for n in roots if n]
                        self._roots_cache.sort(key=lambda n: n.id)
                    return list(self._roots_cache)
                else:
                    return self._children_from_links(parent_id)

        repo = _DocStoreRepo(self.doc_store)
        root_id = self.current_doc_id
        self.tree_win = open_tree_view(self, repo=repo, on_open_doc=self._on_link_click, root_doc_id=root_id)

    def _apply_opml_expand_depth(self):
        """Expand OPML tree in TreeView window to preferred depth."""
        win = getattr(self, "tree_win", None)
        if not win or not win.winfo_exists():
            return
        if hasattr(win, "_expand_to_depth"):
            win._expand_to_depth(self.opml_expand_depth)
            return
        tree = getattr(win, "tree", None)
        if not tree:
            return

        def walk(iid: str, depth: int):
            if depth >= self.opml_expand_depth:
                return
            win.tree.item(iid, open=True)
            for c in win.tree.get_children(iid):
                walk(c, depth + 1)

        for top in tree.get_children(""):
            walk(top, 0)
        if hasattr(win, "_update_numbering"):
            win._update_numbering()

    # ---- Tri Action Ask   ----
    
    # ---- Tri Action Ask ----
    def ask_tri_action(self):
        """
        Run the tri-model pipeline on the current selection (or whole doc if no selection),
        create a new "Tri Synthesis" document, and insert a markdown link [label](doc:ID)
        into the source document. Rendering/styling of links is handled by hypertext_parser.
        """
        try:
            # 1) Determine current doc and selection
            doc_id = getattr(self, "current_doc_id", None)
            if not doc_id:
                messagebox.showinfo("FunKit", "Select a document first.")
                return

            # Try to get selected text if any
            sel_text = ""
            try:
                start = self.text.index(tk.SEL_FIRST)  # type: ignore[attr-defined]
                end = self.text.index(tk.SEL_LAST)     # type: ignore[attr-defined]
                sel_text = self.text.get(start, end).strip()  # type: ignore[attr-defined]
            except Exception:
                sel_text = ""

            # Fallback to whole document body
            if sel_text:
                user_text = sel_text
            else:
                row = self.doc_store.get_document(doc_id)  # uses doc_store, not GUI rendering
                user_text = row["body"] if isinstance(row, dict) else str(row)

            if not isinstance(user_text, str) or not user_text.strip():
                messagebox.showinfo("FunKit", "Nothing to analyze in this document.")
                return

            # 2) Load memory and ensure executor
            conn = self.doc_store.get_connection()
            memory = get_memory(conn, key="global")

            if not hasattr(self, "executor"):
                self.executor = ThreadPoolExecutor(max_workers=2)

            if hasattr(self, "set_status"):
                self.set_status("Running 3-model synthesis…")

            # 3) Run pipeline in background
            fut = self.executor.submit(run_tri_pipeline, user_text, memory)

            def on_done(f):
                try:
                    out = f.result()
                except Exception as e:
                    if hasattr(self, "set_status"):
                        self.set_status("Ready")
                    messagebox.showerror("FunKit", f"Tri-model error: {e}")
                    return

                # 4) Create new doc with final synthesis
                new_id = self.doc_store.add_document("Tri Synthesis", out.final)

                # 5) Update memory breadcrumbs
                memory.setdefault("recent_immediate", [])
                memory["recent_immediate"] = (memory["recent_immediate"] + [out.immediate])[-10:]
                set_memory(conn, memory, key="global")

                # 6) Insert a **markdown** link only (no GUI styling; hypertext_parser handles it)
                label = sel_text if sel_text else "See synthesis"
                link_md = f"[{label}](doc:{new_id})"

                if sel_text:
                    # Replace selected text with link in the widget
                    try:
                        self.text.delete(start, end)  # type: ignore[attr-defined]
                        self.text.insert(start, link_md)  # type: ignore[attr-defined]
                    except Exception:
                        # Fallback: replace first occurrence in stored body
                        body = self.doc_store.get_document(doc_id)["body"]
                        body = body.replace(sel_text, link_md, 1)
                        self.doc_store.update_document(doc_id, body)
                else:
                    # Append at end of widget
                    try:
                        self.text.insert(tk.END, "\n" + link_md)  # type: ignore[attr-defined]
                    except Exception:
                        body = self.doc_store.get_document(doc_id)["body"]
                        body = (body or "") + "\n" + link_md
                        self.doc_store.update_document(doc_id, body)

                # 7) Persist updated body from widget (best effort)
                try:
                    new_body = self.text.get("1.0", tk.END)  # type: ignore[attr-defined]
                    self.doc_store.update_document(doc_id, new_body)
                except Exception:
                    pass

                # 8) Refresh UI
                try:
                    self._refresh_sidebar()
                except Exception:
                    pass
                try:
                    self._render_document(self.doc_store.get_document(doc_id))
                except Exception:
                    pass

                if hasattr(self, "set_status"):
                    self.set_status("Ready")

            # Schedule Tk-safe callback
            self.after(0, lambda: fut.add_done_callback(lambda _f: self.after(0, on_done, _f)))
        except Exception as e:
            if hasattr(self, "set_status"):
                self.set_status("Ready")
            messagebox.showerror("FunKit", f"ASK (Tri) failed: {e}")

    def _ensure_opml_widgets(self):
        """Create (or reuse) the OPML widgets embedded in the document pane."""
        if hasattr(self, "_opml_frame") and self._opml_frame.winfo_exists():
            return
        pane = self.text.master  # the grid container created in _build_main_pane
        self._opml_frame = tk.Frame(pane)
        self._opml_frame.grid(row=0, column=0, sticky="nswe")
        # Toolbar for OPML mode
        tb = tk.Frame(self._opml_frame)
        tb.pack(side=tk.TOP, fill=tk.X)
        self._opml_show_nums = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="Show Numbers", variable=self._opml_show_nums, command=self._opml_update_numbering).pack(
            side=tk.LEFT, padx=6
        )
        # Treeview for OPML
        self._opml_tree = ttk.Treeview(self._opml_frame, columns=("num",), show="tree headings")
        self._opml_tree.heading("num", text="No.")
        self._opml_tree.column("num", width=90, minwidth=60, stretch=False, anchor="e")
        vsb = ttk.Scrollbar(self._opml_frame, orient="vertical", command=self._opml_tree.yview)
        hsb = ttk.Scrollbar(self._opml_frame, orient="horizontal", command=self._opml_tree.xview)
        self._opml_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._opml_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

    def _show_opml(self):
        self._ensure_opml_widgets()
        # Hide text view (uses grid)
        if self.text.winfo_manager():
            self.text.grid_remove()
        self._hide_image()
        self._opml_frame.lift()
        self._opml_frame.grid()

    def _hide_opml(self):
        if hasattr(self, "_opml_frame") and self._opml_frame.winfo_exists():
            self._opml_frame.grid_remove()
        # Restore text
        if not self.text.winfo_manager():
            self.text.grid(row=0, column=0, sticky="nswe")

    def _render_opml_from_string(self, s: str):
        """Parse OPML XML from a string and render it into the embedded tree."""
        try:
            if isinstance(s, (bytes, bytearray)):
                s = s.decode("utf-8", errors="replace")
            s = s.lstrip("\ufeff\r\n\t ")  # strip BOM/whitespace
            root = ET.fromstring(s)
        except Exception as e:
            print("[WARN] OPML parse failed:", e)
            # Fall back to text view
            self._hide_opml()
            self.text.delete("1.0", tk.END)
            self.text.insert(tk.END, s or "")
            return
        if root.tag.lower() != "opml":
            self._hide_opml()
            self.text.delete("1.0", tk.END)
            self.text.insert(tk.END, s or "")
            return

        # It's OPML; render
        self._show_opml()
        # Clear previous content
        for iid in self._opml_tree.get_children(""):
            self._opml_tree.delete(iid)
        # Find <body> and its <outline> children
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
                if c.tag.lower() in {"outline", "node", "item"}:
                    insert_elem(iid, c)

        for e in outlines:
            if e.tag.lower() in {"outline", "node", "item"}:
                insert_elem("", e)

        # Auto-expand and number
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
        show = bool(self._opml_show_nums.get())
        if show:
            self._opml_tree.column("num", width=90, minwidth=60, stretch=False, anchor="e")
        else:
            self._opml_tree.column("num", width=0, minwidth=0, stretch=False)
            def clear(iid=""):
                for c in self._opml_tree.get_children(iid):
                    self._opml_tree.set(c, "num", "")
                    clear(c)
            clear()
            return

        def renumber(iid="", prefix=None):
            if prefix is None:
                prefix = []
            kids = self._opml_tree.get_children(iid)
            for idx, c in enumerate(kids, start=1):
                parts = prefix + [idx]
                self._opml_tree.set(c, "num", ".".join(str(n) for n in parts))
                renumber(c, parts)

        renumber("")

    # ---------------- Image ops ----------------

    def _looks_like_image(self, title: str) -> bool:
        return title.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp"))

    def _show_image_bytes(self, raw: bytes):
        from io import BytesIO
        pil = Image.open(BytesIO(raw))
        # Size to window-ish
        w, h = max(100, self.winfo_width() - 40), max(100, self.winfo_height() - 40)
        pil.thumbnail((w, h))
        self._last_pil_img = pil
        self._last_tk_img = ImageTk.PhotoImage(pil)
        self.img_label.configure(image=self._last_tk_img)

    def _hide_image(self):
        if self.img_label and self.img_label.winfo_manager():
            self.img_label.configure(image="")

    def _toggle_image(self):
        if not self._last_pil_img:
            return
        if not self._image_enlarged:
            win = tk.Toplevel(self)
            win.title("Image Preview")
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            iw, ih = self._last_pil_img.size
            win.geometry(f"{min(iw, sw)}x{min(ih, sh)}")
            canvas = tk.Canvas(win)
            hbar = ttk.Scrollbar(win, orient="horizontal", command=canvas.xview)
            vbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
            canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set, scrollregion=(0, 0, iw, ih))
            canvas.grid(row=0, column=0, sticky="nsew")
            hbar.grid(row=1, column=0, sticky="we")
            vbar.grid(row=0, column=1, sticky="ns")
            win.grid_rowconfigure(0, weight=1)
            win.grid_columnconfigure(0, weight=1)
            tk_img = ImageTk.PhotoImage(self._last_pil_img)
            canvas.create_image(0, 0, anchor="nw", image=tk_img)
            canvas.image = tk_img
            win.bind("<Button-1>", lambda e: self._toggle_image())
            self._image_enlarged = True
        else:
            default = f"document_{self.current_doc_id}.png"
            path = filedialog.asksaveasfilename(
                title="Save Image",
                initialfile=default,
                defaultextension=".png",
                filetypes=[("PNG", "*.png"), ("All Files", "*.*")],
            )
            if path:
                try:
                    self._last_pil_img.save(path)
                    messagebox.showinfo("Save Image", f"Image saved to:\n{path}")
                except Exception as e:
                    messagebox.showerror("Save Image", f"Error saving image:{e}")
            self._image_enlarged = False

    def _handle_image(self):
        try:
            start = self.text.index(tk.SEL_FIRST)
            end = self.text.index(tk.SEL_LAST)
            prompt = self.text.get(start, end).strip()
        except tk.TclError:
            messagebox.showwarning("IMAGE", "Please select some text first.")
            return

        def wrk():
            try:
                pil = image_generator.generate_image(prompt)
                self._last_pil_img = pil
                thumb = pil.copy()
                thumb.thumbnail((800, 400))
                self._last_tk_img = ImageTk.PhotoImage(thumb)
                self._image_enlarged = False
                self.after(0, lambda: self.img_label.configure(image=self._last_tk_img))
            except Exception as e:
                err = str(e)  # capture inside the except scope
                self.after(0, lambda err=err: messagebox.showerror("Image Error", err))

        threading.Thread(target=wrk, daemon=True).start()

    # ---------------- Import/Export ----------------

    def _import_doc(self):
        path = filedialog.askopenfilename(title="Import", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not path:
            return
        body = Path(path).read_text(encoding="utf-8")
        title = Path(path).stem
        nid = self.doc_store.add_document(title, body)
        self.logger.info(f"Imported {nid}")
        self._refresh_sidebar()
        doc = self.doc_store.get_document(nid)
        if doc:
            self._render_document(doc)

    def _export_doc(self):
        """Robust export: picks sensible default extension, writes bytes for binary and text for text."""
        from tkinter import filedialog, messagebox
        from pathlib import Path

        if getattr(self, "current_doc_id", None) is None:
            messagebox.showwarning("Export", "No document selected.")
            return

        # Fetch and normalize
        doc = self.doc_store.get_document(self.current_doc_id)
        if hasattr(doc, "keys"):  # sqlite3.Row-like
            title = doc["title"] if "title" in doc.keys() else "Document"
            body = doc["body"] if "body" in doc.keys() else ""
        elif isinstance(doc, dict):
            title = doc.get("title") or "Document"
            body = doc.get("body") or ""
        else:  # tuple/list row: (id, title, body, ...)
            title = doc[1] if len(doc) > 1 else "Document"
            body = doc[2] if len(doc) > 2 else ""

        # Infer extension/filetypes
        ext = ".txt"
        filetypes = [("Text", "*.txt"), ("All files", "*.*")]
        if isinstance(body, (bytes, bytearray)):
            b = bytes(body)
            if b.startswith(b"\x89PNG\r\n\x1a\n"):
                ext, filetypes = ".png", [("PNG image", "*.png"), ("All files", "*.*")]
            elif b.startswith(b"\xff\xd8\xff"):
                ext, filetypes = ".jpg", [("JPEG image", "*.jpg;*.jpeg"), ("All files", "*.*")]
            elif b[:6] in (b"GIF87a", b"GIF89a"):
                ext, filetypes = ".gif", [("GIF image", "*.gif"), ("All files", "*.*")]
            elif b.startswith(b"%PDF-"):
                ext, filetypes = ".pdf", [("PDF", "*.pdf"), ("All files", "*.*")]
            elif b[:4] == b"RIFF" and b[8:12] == b"WEBP":
                ext, filetypes = ".webp", [("WebP", "*.webp"), ("All files", "*.*")]
            else:
                try:
                    b.decode("utf-8")
                    ext, filetypes = ".txt", [("Text", "*.txt"), ("All files", "*.*")]
                except Exception:
                    ext, filetypes = ".bin", [("Binary", "*.bin"), ("All files", "*.*")]
        else:
            s = (body or "").lstrip()
            low = s.lower()
            if low.startswith("<opml"):
                ext, filetypes = ".opml", [("OPML", "*.opml"), ("XML", "*.xml"), ("All files", "*.*")]
            elif low.startswith("<html") or ("<body" in low) or ("<div" in low):
                ext, filetypes = ".html", [("HTML", "*.html;*.htm"), ("All files", "*.*")]
            elif low.startswith("<svg"):
                ext, filetypes = ".svg", [("SVG", "*.svg"), ("All files", "*.*")]
            else:
                ext, filetypes = ".txt", [("Text", "*.txt"), ("All files", "*.*")]

        # Ask destination
        safe = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in (title or "Document")).strip() or "Document"
        path = filedialog.asksaveasfilename(
            title="Export Document",
            defaultextension=ext,
            initialfile=f"{safe}{ext}",
            filetypes=filetypes,
        )
        if not path:
            return

        # Write
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            if isinstance(body, (bytes, bytearray)) and ext not in (".txt", ".opml", ".html", ".svg", ".xml"):
                Path(path).write_bytes(bytes(body))
            else:
                if isinstance(body, (bytes, bytearray)):
                    # Convert bytes→text if the user chose a texty extension
                    try:
                        text_out = body.decode("utf-8")
                    except Exception:
                        try:
                            from modules.hypertext_parser import render_binary_as_text
                            text_out = render_binary_as_text(body, title or "Document")
                        except Exception:
                            text_out = body.decode("utf-8", errors="replace")
                    Path(path).write_text(text_out, encoding="utf-8", newline="\n")
                else:
                    Path(path).write_text(body or "", encoding="utf-8", newline="\n")
            messagebox.showinfo("Export", f"Saved:\n{path}")
        except Exception as e:
            messagebox.showerror("Export", f"Could not save:\n{e}")

    def _import_directory(self):
        dir_path = filedialog.askdirectory(title="Select Folder to Import")
        if not dir_path:
            return
        imported, skipped = import_text_files_from_directory(dir_path, self.doc_store)
        msg = f"Imported {imported} file(s), skipped {skipped}."
        print("[INFO]", msg)
        messagebox.showinfo("Directory Import", msg)
        self._refresh_sidebar()

    def export_and_launch_server(self):
        export_path = Path("exported_docs")
        export_path.mkdir(exist_ok=True)
        for doc in self.doc_store.get_document_index():
            data = dict(self.doc_store.get_document(doc["id"]))
            if data:
                data = sanitize_doc(data)
                with open(export_path / f"{data['id']}.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)

        def launch():
            fp = Path("modules") / "flask_server.py"
            if fp.exists():
                subprocess.Popen([sys.executable, str(fp)])

        threading.Thread(target=launch, daemon=True).start()
        messagebox.showinfo("Server Started", "Flask server launched at http://127.0.0.1:5050")

    def _save_binary_as_text(self):
        selected_item = self.sidebar.selection()
        if not selected_item:
            return
        doc_id_str = self.sidebar.item(selected_item, "values")[0]
        if not str(doc_id_str).isdigit():
            print(f"Warning: selected text is not a valid integer '{doc_id_str}'")
            return
        doc_id = int(doc_id_str)
        doc = self.doc_store.get_document(doc_id)
        if not doc or len(doc) < 3:
            return
        body = doc[2]
        if isinstance(body, bytes) or ("\x00" in str(body)):
            print("Binary detected, converting to text using render_binary_as_text.")
            body = render_binary_as_text(body)
            self.doc_store.update_document(doc_id, body)
            self._render_document(self.doc_store.get_document(doc_id))
        else:
            print("Document is already text. Skipping overwrite.")
        content = self.processor.get_strings_content(doc_id)
        self.doc_store.update_document(doc_id, content)
        doc = self.doc_store.get_document(doc_id)
        self._render_document(doc)

    # ---------------- Open OPML (import) ----------------

    def _open_opml_from_main(self):
        path = filedialog.askopenfilename(
            title="Open OPML/XML", filetypes=[("OPML / XML", "*.opml *.xml"), ("All files", "*.*")]
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
        self._refresh_sidebar()
        self.current_doc_id = new_id
        doc = self.doc_store.get_document(new_id)
        if doc:
            self._render_document(doc)
        if getattr(self, "tree_win", None) and self.tree_win.winfo_exists():
            try:
                self.tree_win.load_opml_file(path)
                self.tree_win.deiconify()
                self.tree_win.lift()
                self._apply_opml_expand_depth()
            except Exception:
                pass

    # ---------------- Rendering ----------------

    def _render_document(self, doc):
        """Render a document once, parse green links, and auto-render OPML when detected."""
        # Normalize doc body
        body = doc.get("body") if isinstance(doc, dict) else (doc[2] if len(doc) > 2 else "")
        if isinstance(body, str):
            b_norm = body.lstrip("\ufeff\r\n\t ")
            if "<opml" in b_norm.lower():
                self._render_opml_from_string(b_norm)
                return

        # Plain text or other
        self._hide_opml()
        self.text.delete("1.0", tk.END)

        # bytes -> placeholder
        if isinstance(body, (bytes, bytearray)):
            self.text.insert(tk.END, "[binary document]")
            return

        # very large text -> placeholder
        if isinstance(body, str) and len(body) > 200_000:
            self.text.insert(tk.END, "[large binary-like document]")
            return

        # Show and parse links
        self.text.insert(tk.END, body or "")
        hypertext_parser.parse_links(self.text, body or "", self._on_link_click)

    def _on_link_click(self, doc_id):
        if self.current_doc_id is not None:
            self.history.append(self.current_doc_id)
        self.current_doc_id = doc_id
        doc = self.doc_store.get_document(doc_id)
        if doc:
            self._render_document(doc)

    def _on_delete_clicked(self):
        """Delete the currently selected document from the sidebar and clear the pane."""
        sel = self.sidebar.selection()
        if not sel:
            messagebox.showwarning("Delete", "No document selected.")
            return
        item = self.sidebar.item(sel[0])
        vals = item.get("values") or []
        if not vals:
            messagebox.showerror("Delete", "Invalid selection.")
            return
        try:
            nid = int(vals[0])
        except (ValueError, TypeError):
            messagebox.showerror("Delete", "Invalid document ID.")
            return
        if not messagebox.askyesno("Confirm Delete", f"Delete document ID {nid}?"):
            return
        try:
            self.doc_store.delete_document(nid)
        except Exception as e:
            messagebox.showerror("Delete", f"Failed to delete: {e}")
            return
        # Clear UI
        self._refresh_sidebar()
        self.text.delete("1.0", tk.END)
        if hasattr(self, "_opml_frame") and self._opml_frame.winfo_exists():
            self._opml_frame.grid_remove()
        if hasattr(self, "img_label"):
            self.img_label.configure(image="")
        self.current_doc_id = None
        self._last_pil_img = None
        self._last_tk_img = None
        self._image_enlarged = False
        messagebox.showinfo("Deleted", f"Document {nid} has been deleted.")


def sanitize_doc(doc):
    if isinstance(doc["body"], bytes):
        try:
            doc["body"] = doc["body"].decode("utf-8")
        except UnicodeDecodeError:
            doc["body"] = doc["body"].decode("utf-8", errors="replace")
    return doc
