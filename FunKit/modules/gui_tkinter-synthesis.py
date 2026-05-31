from modules import inline_webview as _inlineweb
from modules import opml_nav_helpers as _opmlnav
from modules.provider_registry import registry
import mimetypes
from modules.provider_dropdown import ProviderDropdown
import os
import threading
import logging
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from pathlib import Path
from PIL import ImageTk, Image
import subprocess
import sys
import json
import re
import xml.etree.ElementTree as ET
from modules.ai_singleton import get_ai, set_provider_global
# ---- structured logging for AI requests ----
logger = logging.getLogger("funkit.ai")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    try:
        _fh = logging.FileHandler("ai_query.log", encoding="utf-8")
        _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(_fh)
    except Exception:
        _sh = logging.StreamHandler()
        _sh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(_sh)
# -------------------------------------------

def _bind_provider_hotkeys(self):
    """Bind convenient shortcuts to switch providers.
    Ctrl+Alt+L -> Local, Ctrl+Alt+B -> Baseten, Ctrl+Alt+O -> OpenAI
    """
    try:
        self.bind_all('<Control-Alt-l>', lambda e: self._force_provider('local'))
        self.bind_all('<Control-Alt-b>', lambda e: self._force_provider('baseten'))
        self.bind_all('<Control-Alt-o>', lambda e: self._force_provider('openai'))
    except Exception:
        pass

def _force_provider(self, prov: str):
    try:
        from modules.ai_singleton import set_provider_global
        set_provider_global(prov)
    except Exception:
        pass
    try:
        if hasattr(self, 'ai') and hasattr(self.ai, 'set_provider'):
            self.ai.set_provider(prov)
    except Exception:
        pass
    try:
        if hasattr(self, 'processor') and hasattr(self.processor, 'ai') and hasattr(self.processor.ai, 'set_provider'):
            self.processor.ai.set_provider(prov)
    except Exception:
        pass



# FunKit modules (all live under ./modules)
from modules import hypertext_parser, image_generator, document_store
from modules import aopml_engine
from modules import image_render
from modules.renderer import render_binary_as_text
from modules.logger import Logger
from modules.directory_import import import_text_files_from_directory
from modules.TreeView import open_tree_view
# OPML extras plugin (menu, hotkeys, toolbar buttons, engine helpers)
from modules.opml_extras_plugin import (
    install_opml_extras_into_app,
    _resolve_engine,
    _decode_bytes_best,
)

SETTINGS_FILE = Path("funkit_settings.json")


# ---- network helper (thread-safe: no Tk/SQLite here) ----
def fetch_html_with_fallback(url, max_bytes, connect_to, read_to, budget_s):
    """Do the network I/O only. Returns decoded HTML as str."""
    import time, socket
    start = time.monotonic()

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 FunKit/OPML",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }

    # Try requests if available
    try:
        import requests
        with requests.get(url, headers=headers, timeout=(connect_to, read_to),
                          stream=True, allow_redirects=True) as r:
            r.raise_for_status()
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype and "xml" not in ctype:
                raise RuntimeError(f"Unsupported Content-Type: {ctype or 'unknown'}")
            raw = bytearray()
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    raw.extend(chunk)
                if len(raw) > max_bytes or (time.monotonic() - start) > budget_s:
                    break
        return _decode_bytes_best(bytes(raw))
    except Exception:
        pass

    # Fallback: urllib
    import urllib.request
    old_t = socket.getdefaulttimeout()
    socket.setdefaulttimeout(read_to)
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=connect_to) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype and "xml" not in ctype:
                raise RuntimeError(f"Unsupported Content-Type: {ctype or 'unknown'}")
            raw = bytearray()
            while True:
                if (time.monotonic() - start) > budget_s:
                    break
                chunk = resp.read(65536)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > max_bytes:
                    break
    finally:
        socket.setdefaulttimeout(old_t)

    return _decode_bytes_best(bytes(raw))


# ---------------------------------------------------------------------
# Grid-safe ProviderSwitcher (no pack; tolerant of return shapes)
# ---------------------------------------------------------------------
class ProviderSwitcher_DEPRECATED(ttk.Frame):
# ---------------------------------------------------------------------
    pass

# Marquee / banner (grid-friendly)
# ---------------------------------------------------------------------
class MarqueeStatusBar(ttk.Frame):
    """
    Grid‑only scrolling status bar. Call .set_text(...) for a static line,
    or .push(msg) to append to the rotating queue. Use .start()/.stop() to control.
    """
    def __init__(self, parent, height=22, speed_px=2, interval_ms=40, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)

        self._items: list[str] = []
        self._idx = 0
        self._text_item = None
        self._x = 0
        self._speed = speed_px
        self._interval = interval_ms
        self._running = False
        self._cur_text = ""

        self.bind("<Configure>", lambda e: self._redraw())

    def _redraw(self):
        w = self.winfo_width()
        self.canvas.config(width=w)
        self._draw_text(self._cur_text or " ")

    def _draw_text(self, text: str):
        self.canvas.delete("all")
        self._cur_text = text
        w = self.winfo_width()
        pad = 40  # gap between repeats
        self._text_item = self.canvas.create_text(w, 12, anchor="w", text=text)
        bbox = self.canvas.bbox(self._text_item) or (0, 0, 0, 0)
        text_w = bbox[2] - bbox[0]
        self.canvas.create_text(w + text_w + pad, 12, anchor="w", text=text)
        self._x = w

    def _tick(self):
        if not self._running:
            return
        for item in self.canvas.find_all():
            self.canvas.move(item, -self._speed, 0)
        items = self.canvas.find_all()
        if items:
            bbox = self.canvas.bbox(items[0])
            if bbox and bbox[2] < 0:
                self._advance_queue()
        self.after(self._interval, self._tick)

    def _advance_queue(self):
        if self._items:
            self._idx = (self._idx + 1) % len(self._items)
            nxt = self._items[self._idx]
        else:
            nxt = self._cur_text
        self._draw_text(nxt)

    def set_text(self, text: str):
        self._items = [text]
        self._idx = 0
        self._draw_text(text)

    def push(self, text: str):
        if not text:
            return
        self._items.append(text)
        if len(self._items) == 1:
            self.set_text(text)

    def replace_queue(self, messages: list[str]):
        self._items = [m for m in messages if m]
        self._idx = 0
        self._draw_text(self._items[0] if self._items else " ")

    def start(self):
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self):
        self._running = False


class DemoKitGUI(tk.Tk):


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
                messagebox.showinfo("Saved", f"OPML saved to: {path}\nUse OPEN OPML to import if needed.")
        except Exception:
            pass
        print("[doc-store] create fell back. Tried:", "; ".join(tried))
        return None
        def _open_url_to_opml(self):
            import tkinter as tk
            from tkinter import simpledialog, messagebox
            try:
                from modules import aopml_engine as eng
            except Exception:
                import modules.aopmlengine as eng
        url = simpledialog.askstring('URL → OPML','Enter a URL to import as OPML:')
        if not url:
            return
        try:
            opml = eng.url_to_opml(url)
        except Exception as e:
            messagebox.showerror('Import failed', str(e))
            return
        try:
            doc_id = self._create_doc_portable(title=f'OPML from {url}', content=opml, content_type='opml')
            self.refresh_list_and_open(doc_id)
        except Exception as e:
            messagebox.showerror('Save failed', str(e))
            return

    """
    Grid-only provider switcher for FunKit (A/B/C).
    Works with modules.provider_switch.{get_current_provider,set_current_provider,list_labels}.
    """
    SLOTS = ("A", "B", "C")

    def __init__(self, parent, status_cb=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.status_cb = status_cb
        self.columnconfigure(2, weight=1)

        ttk.Label(self, text="Provider:").grid(row=0, column=0, padx=(6, 4), pady=4, sticky="w")

        self.var_slot = tk.StringVar()
        self.cbo = ttk.Combobox(self, width=6, textvariable=self.var_slot,
                                state="readonly", values=list(self.SLOTS))
        self.cbo.grid(row=0, column=1, padx=(0, 8), pady=4, sticky="w")
        self.cbo.bind("<<ComboboxSelected>>", self._on_slot_changed)

        self.var_details = tk.StringVar(value="")
        self.lbl = ttk.Label(self, textvariable=self.var_details)
        self.lbl.grid(row=0, column=2, padx=(0, 8), pady=4, sticky="ew")

        self._refresh_from_config()

    # ---- robust helpers ----

    def _labels_map(self) -> dict:
        try:
            labels = list_labels()
        except Exception:
            labels = None
        if isinstance(labels, dict):
            return {str(k).upper(): str(v) for k, v in labels.items()}
        if isinstance(labels, list) and all(isinstance(x, str) for x in labels):
            return {s: labels[i] for i, s in enumerate(self.SLOTS) if i < len(labels)}
        if isinstance(labels, list) and all(isinstance(x, (tuple, list)) and len(x) >= 2 for x in labels):
            out = {}
            for key, val, *_ in labels:
                ks = str(key).upper()
                if ks in self.SLOTS:
                    out[ks] = str(val)
            return out
        return {s: f"Slot {s}" for s in self.SLOTS}

    def _normalize_current(self):
        """
        Normalize get_current_provider() return to (slot:str, meta:dict).
        Accepts:
          - ("A", {"type":...})
          - ("A", "Local", {"type":...})
          - {"current":"A", "A":{...}, ...}
          - "A"
        """
        try:
            res = get_current_provider()
        except Exception:
            return "A", {}
        # tuple/list
        if isinstance(res, (tuple, list)):
            slot = None
            meta = {}
            for item in res:
                if slot is None and isinstance(item, str):
                    slot = item
                if isinstance(item, dict):
                    if any(k in item for k in ("type", "model", "base_url")):
                        meta = item
            slot = (slot or "A").upper()
            if slot not in self.SLOTS:
                slot = "A"
            return slot, (meta or {})
        # dict form
        if isinstance(res, dict):
            slot = str(res.get("current", "A")).upper()
            if slot not in self.SLOTS:
                slot = "A"
            meta = res.get(slot, {})
            if not isinstance(meta, dict):
                meta = {}
            return slot, meta
        # string form
        if isinstance(res, str):
            slot = res.upper()
            if slot not in self.SLOTS:
                slot = "A"
            return slot, {}
        return "A", {}

    # ---- UI updates ----

    def _refresh_from_config(self):
        cur_slot, meta = self._normalize_current()
        self.var_slot.set(cur_slot)
        self._update_details(cur_slot, meta)

    def _update_details(self, slot: str, meta: dict | None = None):
        labels = self._labels_map()
        label = labels.get(slot, f"Slot {slot}")
        meta = meta or {}
        typ = meta.get("type", "?")
        model = meta.get("model", "?")
        base = meta.get("base_url", "")
        self.var_details.set(f"{label} — {typ} — {model} — {base}")

    # ---- events ----

    def _on_slot_changed(self, _evt=None):
        slot = self.var_slot.get()
        try:
            set_current_provider(slot)
            cur_slot, meta = self._normalize_current()
            self.var_slot.set(cur_slot)
            self._update_details(cur_slot, meta)
            if callable(self.status_cb):
                self.status_cb(f"Provider slot set to {cur_slot}")
        except Exception as e:
            self.var_details.set(f"Failed to switch: {e}")
            if callable(self.status_cb):
                self.status_cb(f"Provider switch failed: {e}")


    def _debug_url_to_opml(self):
        import traceback
        from tkinter import messagebox
        try:
            print('[URL→OPML] menu clicked')
            self.after(0, lambda: None)  # ensure we’re in mainloop
            self._open_url_to_opml()
        except Exception as e:
            tb = traceback.format_exc()
            print('[URL→OPML] ERROR:', tb)
            try:
                messagebox.showerror('URL → OPML failed', tb)
            except Exception:
                pass

    def _provider_status_cb(self, lbl, mdl):
        # Map UI label -> internal provider key
        label = (str(lbl) or '').lower()
        if 'openai' in label:
            _prov = 'openai'
        elif 'baseten' in label or 'mistral' in label:
            _prov = 'baseten'
        elif 'local' in label or 'llama' in label:
            _prov = 'local'
        else:
            _prov = 'openai'

        # Remember selection (for UI/logs)
        self._last_provider_label = str(lbl)
        self._last_provider_model = str(mdl)

        # Update ticker
        cb = getattr(self, 'set_ticker_text', None)
        if callable(cb):
            cb(f"{lbl} • {mdl}")
        else:
            self.status(f"{lbl} • {mdl}")

        # Propagate to the *shared* AI instance and any attached processor
        try:
            set_provider_global(_prov)
        except Exception:
            pass
        try:
            if hasattr(self, 'ai') and hasattr(self.ai, 'set_provider'):
                self.ai.set_provider(_prov)
        except Exception:
            pass
        try:
            if hasattr(self, 'processor') and hasattr(self.processor, 'ai') and hasattr(self.processor.ai, 'set_provider'):
                self.processor.ai.set_provider(_prov)
        except Exception:
            pass

    def __init__(self, doc_store, processor):
        # --- Ensure GUI constants exist (auto-inserted) ---  ##__GUI_CONST_GUARD__
        # Use __dict__ to avoid Tkinter __getattr__ recursion
        if 'SIDEBAR_WIDTH' not in self.__dict__:
            self.SIDEBAR_WIDTH = 260
        if 'EDITOR_MINWIDTH' not in self.__dict__:
            self.EDITOR_MINWIDTH = 480
        if 'TOPBAR_HEIGHT' not in self.__dict__:
            self.TOPBAR_HEIGHT = 36
        # ---------------------------------------------------
        try: self.bind("<Control-Shift-I>", self._on_import_images_clicked)
        except Exception: pass
        try: self.bind("<Control-Shift-E>", self._export_current_images_aware)
        except Exception: pass
        super().__init__()
        self.doc_store = doc_store
        self.processor = processor
        self.logger: Logger = getattr(processor, "logger", Logger())
        self.current_doc_id: int | None = None
        self.history: list[int] = []

        self.title("Engelbart Journal – DemoKit")
        self.geometry("1200x800")

        # ---- Layout: row0=banner, row1=toolbar, row2=content
        self.columnconfigure(0, minsize=self.SIDEBAR_WIDTH, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=0)  # banner
        self.rowconfigure(1, weight=0)  # toolbar
        self.rowconfigure(2, weight=1)  # content

        # ---- Banner (row=0)
        self.banner = MarqueeStatusBar(self, height=22, speed_px=2, interval_ms=35)
        self.banner.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.banner.replace_queue([
            "FunKit ready — type commands with $ …  (Try:  $ HELP  |  $ LIST  |  Paste a URL)",
            "Tip: Select text and click ASK to create a linked AI note",
            "Use Provider A/B/C to flip between Local / Baseten / OpenAI",
        ])
        self.banner.start()

        # ---- Top toolbar (row=1)
        self.topbar = ttk.Frame(self)
        self.topbar.grid(row=1, column=0, columnspan=2, sticky="ew")

        # Provider switch (left)
        self.provider_switch = ProviderDropdown(self.topbar, status_cb=self._provider_status_cb)
        self.provider_switch.grid(row=0, column=0, sticky="w")

        # URL/Search entry (right side)
        self.topbar.grid_columnconfigure(1, weight=1)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(self.topbar, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=(8, 4))
        self.url_entry.bind("<Return>", self._on_url_entered)
        self.go_btn = ttk.Button(self.topbar, text="Go", command=self._on_url_entered)
        self.go_btn.grid(row=0, column=2, sticky="e", padx=(4, 6))

        # image state
        self._last_pil_img: Image.Image | None = None
        self._last_tk_img: ImageTk.PhotoImage | None = None
        self._image_enlarged: bool = False

        # ---- Settings ----
        self.settings = self._load_settings()
        self.opml_expand_depth: int = int(self.settings.get("opml_expand_depth", 2))

        # Build UI
        self._build_sidebar()
        self._build_main_pane()
        self._build_context_menu()

        # --- Menubar ---
        menubar = tk.Menu(self)

        # Tools menu & OPML submenu (added by patch)
        tools_menu = tk.Menu(menubar, tearoff=0)
        opml_menu = tk.Menu(tools_menu, tearoff=0)
        opml_menu.add_command(label='URL → Import as OPML', command=lambda s=self: s._debug_url_to_opml())
        tools_menu.add_cascade(label='OPML', menu=opml_menu)
        menubar.add_cascade(label='Tools', menu=tools_menu)
        # File menu
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Import", command=self._import_doc)
        filemenu.add_command(label="Export Current", command=self._export_doc)
        filemenu.add_separator()
        filemenu.add_command(label="Export to Intraweb", command=self.export_and_launch_server)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)
        try:
            filemenu.add_command(label="Import Images...", command=self._on_import_images_clicked)
            filemenu.add_command(label="Export Image...", command=self._export_current_images_aware)
        except Exception:
            pass

        # View menu (Tree + OPML depth)
        viewmenu = tk.Menu(menubar, tearoff=0)
        viewmenu.add_command(label="Document Tree\tCtrl+T", command=self.on_tree_button)
        viewmenu.add_separator()
        viewmenu.add_command(label="Set OPML Expand Depth…", command=self._set_opml_expand_depth)
        menubar.add_cascade(label="View", menu=viewmenu)

        self.config(menu=menubar)
        
        # Attach OPMLExtras plugin explicitly (adds Tools → OPML → Open URL as OPML)
        try:
            from modules import opml_extras_plugin
            opml_extras_plugin.attach(self)
        except Exception as e:
            print("[WARN] OPMLExtras attach failed:", e)
            self.bind("<Control-t>", lambda e: self.on_tree_button())

        # Install OPML plugin (menu, hotkeys, toolbar buttons)
        try:
            install_opml_extras_into_app(self)
        except Exception as e:
            print("[WARN] Failed to install OPML extras:", e)

        self._refresh_sidebar()
        # initial status
        try:
            self.status(f"Loaded {len(self.doc_store.get_document_index())} documents.")
        except Exception:
            pass

    # ---------------- Status -> banner ----------------
    def status(self, msg: str):
        try:
            self.banner.push(str(msg))
        except Exception:
            pass

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
        win = getattr(self, "tree_win", None)
        if win and win.winfo_exists():
            self._apply_opml_expand_depth()

    # ---------------- Sidebar ----------------

    def _build_sidebar(self):
        frame = tk.Frame(self)
        frame.grid(row=2, column=0, sticky="nswe")
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
        pane.grid(row=2, column=1, sticky="nswe", padx=4, pady=4)
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
        self.toolbar = btns   # plugins can attach buttons here

        acts = [
            ("TREE", self.on_tree_button),
            ("OPEN OPML", self._open_opml_from_main),
            ("ASK", self._handle_ask),
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

    # ---------------- URL/Search bar handlers ----------------

    def _on_url_entered(self, event=None):
        """
        Accept either:
          - Command: starts with '$' → legacy/modern command processors
          - URL (scheme or bare hostname) → fetch & import as OPML (no dialog)
          - Otherwise: treat as a 'search-like' input and store a stub doc
        """
        text = (self.url_var.get() or "").strip()
        if not text:
            return

        # Commands
        if text.startswith("$"):
            self._handle_command(text[1:].lstrip())
            return

        # URL-ish (with scheme or bare host)
        if text.startswith(("http://", "https://", "qrc://", "qrc:///")) or ("." in text and " " not in text):
            url = text if text.startswith(("http", "qrc://")) else ("http://" + text)
            self._import_url_direct_as_opml(url)
            return

        # Fallback: basic "search" stub (can wire real search later)
        nid = self.doc_store.add_document(f"Search: {text}", "Type a full URL or start a command with: $ …")
        self._refresh_sidebar()
        self._render_document(self.doc_store.get_document(nid))

    def _import_url_direct_as_opml(self, url: str, max_bytes: int = 600_000,
                                   connect_to: int = 8, read_to: int = 8, budget_s: int = 12):
        """Fetch a single URL → Convert to OPML using the plugin engine; save & render (background thread)."""
        def worker():
            import re
            EC, BOH, BOT = _resolve_engine()
            if EC is None:
                import logging, webbrowser
                logging.warning("AOPML engine not found; falling back to web view")
                try:
                    self.marquee_show("AOPML engine not found -> rendering web view")
                except Exception:
                    pass
                try:
                    self._render_url_in_pane(url)
                except Exception:
                    try:
                        self._render_url_in_pane(url)
                    except Exception:
                        (
                            (self._show_url_in_pane(url) or self._render_with_qt6(url))
                            if hasattr(self, '_render_with_qt6') else webbrowser.open(url)
                        )
                return

            # 1) fetch in background
            try:
                html = fetch_html_with_fallback(url, max_bytes, connect_to, read_to, budget_s)
            except Exception as e:
                self.after(0, lambda e=e: messagebox.showerror("URL → OPML", f"Fetch failed:\n{e}"))
                return

            # 2) build OPML in background
            m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
            title = (m.group(1).strip() if m else url)
            title = re.sub(r"\s+", " ", title)
            opml_title = f"{title} (OPML)"

            try:
                cfg = EC(enable_ai=False, title=opml_title, owner_name=None)
                try:
                    opml_doc = BOH(html or "", cfg)
                except Exception:
                    text_only = re.sub(r"<[^>]+>", " ", html or "", flags=re.S)
                    text_only = re.sub(r"\s+", " ", text_only)
                    opml_doc = BOT(text_only[:max_bytes], cfg)
                xml = opml_doc.to_xml()
            except Exception as e:
                self.after(0, lambda e=e: messagebox.showerror("URL → OPML", f"OPML build failed:\n{e}"))
                return

            # 3) schedule DB + UI on the Tk main thread
            def finish():
                try:
                    nid = self.doc_store.add_document(opml_title, xml)
                    self._refresh_sidebar()
                    self._on_link_click(nid)
                    self.status(f"Imported OPML from URL")
                except Exception as e:
                    messagebox.showerror("URL → OPML", f"DB error:\n{e}")

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- ASK / BACK ----------------

    def _handle_ask(self):
        provider_label = getattr(self, '_last_provider_label', 'unknown')
        provider_model = getattr(self, '_last_provider_model', '')
        logger.info("ASK start | provider=%s | model=%s | prompt_len=%s", provider_label, provider_model, len(selected_text) if 'selected_text' in locals() else 'na')
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
            self.status("AI: reply received")

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

    # ---------------- Command handler for "$ ..." in URL bar ----------------

    def _handle_command(self, cmdline: str):
        """
        Handle commands typed as: $ ...
        Priority:
          1) built-in Phase-5 style commands (NEW/LIST/VIEW/EDIT/DELETE/SAVE/LOAD/HELP/ASK/SUMMARIZE)
          2) legacy modules.commands.CommandProcessor.process(cmdline) (capture stdout)
          3) fallback
        Output is stored as a new document and shown in the pane.
        """
        import io, contextlib, shlex

        def store_output(title: str, body: str | None):
            try:
                nid = self.doc_store.add_document(title, body or "")
                self._refresh_sidebar()
                self._render_document(self.doc_store.get_document(nid))
            except Exception as e:
                messagebox.showerror("Command Error", str(e))

        # --- helpers to read doc content ----
        def _get_doc_body(doc_id: int) -> str:
            row = self.doc_store.get_document(doc_id)
            if not row:
                raise ValueError(f"Document {doc_id} not found")
            if hasattr(row, "keys"):
                return row.get("body", "")
            if isinstance(row, dict):
                return row.get("body", "")
            if isinstance(row, (list, tuple)) and len(row) >= 3:
                return row[2]
            return str(row)

        def builtin(argv: list[str]) -> bool:
            if not argv:
                return False
            cmd = argv[0].upper()

            if cmd == "HELP":
                body = (
                    "FunKit command cheatsheet (type in the top bar prefixed with $):\n\n"
                    "  NEW <title>                   Create a new empty document\n"
                    "  LIST                          List documents (id, title)\n"
                    "  VIEW <id>                     Open a document by id\n"
                    "  EDIT <id>                     Append text to a document (prompt)\n"
                    "  DELETE <id>                   Delete a document\n"
                    "  SAVE <id> <path>              Save a document body to a file\n"
                    "  LOAD <path>                   Import a text file as a new document\n"
                    "  ASK <question>                Ask current provider (AI) a question\n"
                    "  SUMMARIZE <id>                Summarize the given document with AI\n"
                )
                store_output("$ HELP", body)
                return True

            if cmd == "NEW":
                title = " ".join(argv[1:]).strip() or "Untitled"
                store_output(title, "")
                return True

            if cmd == "LIST":
                lines = []
                for row in self.doc_store.get_document_index():
                    did = row.get("id") if isinstance(row, dict) else (row[0] if isinstance(row, (list, tuple)) else None)
                    ttl = row.get("title") if isinstance(row, dict) else (row[1] if isinstance(row, (list, tuple)) else "")
                    lines.append(f"{did:>4}  {ttl}")
                store_output("$ LIST", "\n".join(lines) or "[no documents]")
                return True

            if cmd == "VIEW" and len(argv) >= 2 and argv[1].isdigit():
                doc_id = int(argv[1])
                doc = self.doc_store.get_document(doc_id)
                if doc:
                    self._on_link_click(doc_id)
                else:
                    store_output("$ VIEW", f"Document {doc_id} not found")
                return True

            if cmd == "EDIT" and len(argv) >= 2 and argv[1].isdigit():
                doc_id = int(argv[1])
                extra = simpledialog.askstring("EDIT", f"Append to document {doc_id}:", parent=self)
                if extra is None:
                    return True
                try:
                    body = _get_doc_body(doc_id)
                    self.doc_store.update_document(doc_id, body + ("\n" if body and extra else "") + extra)
                    self._render_document(self.doc_store.get_document(doc_id))
                except Exception as e:
                    store_output("$ EDIT", f"[error] {e}")
                return True

            if cmd == "DELETE" and len(argv) >= 2 and argv[1].isdigit():
                doc_id = int(argv[1])
                try:
                    self.doc_store.delete_document(doc_id)
                    self._refresh_sidebar()
                    if self.current_doc_id == doc_id:
                        self.text.delete("1.0", tk.END)
                        self.current_doc_id = None
                    messagebox.showinfo("Delete", f"Deleted document {doc_id}")
                except Exception as e:
                    store_output("$ DELETE", f"[error] {e}")
                return True

            if cmd == "SAVE" and len(argv) >= 3 and argv[1].isdigit():
                doc_id = int(argv[1]); path = argv[2]
                try:
                    Path(path).write_text(_get_doc_body(doc_id), encoding="utf-8")
                    store_output("$ SAVE", f"Saved {doc_id} → {path}")
                except Exception as e:
                    store_output("$ SAVE", f"[error] {e}")
                return True

            if cmd == "LOAD" and len(argv) >= 2:
                path = " ".join(argv[1:])
                try:
                    content = Path(path).read_text(encoding="utf-8", errors="replace")
                    nid = self.doc_store.add_document(Path(path).name, content)
                    self._refresh_sidebar()
                    self._render_document(self.doc_store.get_document(nid))
                except Exception as e:
                    store_output("$ LOAD", f"[error] {e}")
                return True

            if cmd == "ASK":
                question = " ".join(argv[1:]).strip()
                if not question:
                    store_output("$ ASK", "Usage: ASK <question>")
                    return True
                try:
                    reply = self.processor.ask_question(question)
                except Exception as e:
                    reply = f"[error] {e}"
                store_output(f"ASK: {question}", reply or "[no reply]")
                return True

            if cmd == "SUMMARIZE" and len(argv) >= 2 and argv[1].isdigit():
                doc_id = int(argv[1])
                try:
                    text = _get_doc_body(doc_id)
                    reply = self.processor.ask_question(f"Please summarize the following document:\n{text}")
                except Exception as e:
                    reply = f"[error] {e}"
                store_output(f"Summary of {doc_id}", reply or "[no reply]")
                return True

            return False

        # parse (respect quotes)
        try:
            argv = shlex.split(cmdline)
        except Exception:
            argv = cmdline.split()

        # 1) built-in first
        if builtin(argv):
            return

        # 2) legacy commands.py if available
        try:
            from modules import commands as legacy_cmds
            legacy = legacy_cmds.CommandProcessor(self.doc_store)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                try:
                    legacy.process(cmdline)
                except Exception as e:
                    print(f"[legacy error] {e}")
            out = buf.getvalue()
            if out.strip():
                store_output(f"$ {cmdline}", out)
                return
        except Exception:
            pass

        # 3) default
        store_output(f"$ {cmdline}", "[no handler matched]")

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
                        roots = [self._mk_node(self.ds.get_document(i)) for i in all_ids if i not in referenced]
                        if not roots:
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

    # ---- OPML-in-document-pane helpers ----

    def _ensure_opml_widgets(self):
        """Create (or reuse) the OPML widgets embedded in the document pane."""
        if hasattr(self, "_opml_frame") and self._opml_frame.winfo_exists():
            return
        pane = self.text.master
        self._opml_frame = tk.Frame(pane)
        self._opml_frame.grid(row=0, column=0, sticky="nswe")
        tb = tk.Frame(self._opml_frame)
        tb.pack(side=tk.TOP, fill=tk.X)
        self._opml_show_nums = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="Show Numbers", variable=self._opml_show_nums,
                        command=self._opml_update_numbering).pack(side=tk.LEFT, padx=6)
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
        if self.text.winfo_manager():
            self.text.grid_remove()
        self._hide_image()
        self._opml_frame.lift()
        self._opml_frame.grid()

    def _hide_opml(self):
        if hasattr(self, "_opml_frame") and self._opml_frame.winfo_exists():
            self._opml_frame.grid_remove()
        if not self.text.winfo_manager():
            self.text.grid(row=0, column=0, sticky="nswe")

    def _render_opml_from_string(self, s: str):
        try:
            if isinstance(s, (bytes, bytearray)):
                s = s.decode("utf-8", errors="replace")
            s = s.lstrip("\ufeff\r\n\t ")
            root = ET.fromstring(s)
        except Exception as e:
            print("[WARN] OPML parse failed:", e)
            self._hide_opml()
            self.text.delete("1.0", tk.END)
            self.text.insert(tk.END, s or "")
            return
        if root.tag.lower() != "opml":
            self._hide_opml()
            self.text.delete("1.0", tk.END)
            self.text.insert(tk.END, s or "")
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
                if c.tag.lower() in {"outline", "node", "item"}:
                    insert_elem(iid, c)

        for e in outlines:
            if e.tag.lower() in {"outline", "node", "item"}:
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
        return title.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"))

    def _show_image_bytes(self, raw: bytes):
        from io import BytesIO
        pil = Image.open(BytesIO(raw))
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
                err = str(e)
                self.after(0, lambda err=err: messagebox.showerror("Image Error", err))

        threading.Thread(target=wrk, daemon=True).start()

    # ---------------- Import/Export ----------------

    def _import_doc(self):
        path = filedialog.askopenfilename(title="Import", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not path:
            return
        # Read as UTF-8 text, or fallback to data:image;base64 for images
        try:
            body = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            b = Path(path).read_bytes()
            mime = self._sniff_image_bytes(b)
            if mime is None:
                # Secondary guess by extension
                import mimetypes as _mt
                mt, _ = _mt.guess_type(str(path))
                if mt and mt.startswith("image/"): mime = mt
            if mime:
                import base64 as _b64
                body = f"data:{mime};base64,{_b64.b64encode(b).decode('ascii')}"
            else:
                # Non-image binary: re-raise to keep prior behavior/logging
                raise

        title = Path(path).stem
        nid = self.doc_store.add_document(title, body)
        self.logger.info(f"Imported {nid}")
        self._refresh_sidebar()
        doc = self.doc_store.get_document(nid)
        if doc:
            self._render_document(doc)
        # Fast-path: if we produced a data-URL image, create a doc now and return
        if isinstance(body, str) and body.startswith('data:image/'):
            _doc_id = None
            _title = None
            try:
                from pathlib import Path as _P
                _title = _P(path).name
            except Exception:
                _title = 'image'
            # Try GUI helpers first
            for _name in ('create_document','new_document','add_document_here'):
                _fn = getattr(self, _name, None)
                if callable(_fn):
                    try:
                        _doc_id = _fn(_title, body)
                        break
                    except TypeError:
                        try:
                            _doc_id = _fn({'title': _title, 'body': body})
                            break
                        except Exception:
                            pass
            # Then document_store fallbacks
            if _doc_id is None:
                try:
                    from modules import document_store as _ds
                    for _name in ('create_document','add_document','insert_document','new_document','create','add'):
                        _fn = getattr(_ds, _name, None)
                        if callable(_fn):
                            try:
                                _doc_id = _fn(_title, body)
                                break
                            except TypeError:
                                try:
                                    _doc_id = _fn({'title': _title, 'body': body})
                                    break
                                except Exception:
                                    pass
                except Exception:
                    pass
            if _doc_id is not None:
                try:
                    from tkinter import messagebox as _mb
                    _mb.showinfo('Import', f'Document {_doc_id} created')
                except Exception:
                    pass
                try:
                    if hasattr(self, 'reload_index'): self.reload_index()
                    _tree = getattr(self, 'tree', None)
                    if _tree:
                        for _it in _tree.get_children(''):
                            _vals = _tree.item(_it, 'values')
                            if _vals and str(_vals[0]) == str(_doc_id):
                                _tree.selection_set(_it)
                                _tree.see(_it)
                                if hasattr(self, 'open_doc_by_id'): self.open_doc_by_id(_doc_id)
                                break
                except Exception:
                    pass
                return

    def _export_doc(self):
        if getattr(self, "current_doc_id", None) is None:
            messagebox.showwarning("Export", "No document selected.")
            return

        doc = self.doc_store.get_document(self.current_doc_id)
        if hasattr(doc, "keys"):
            title = doc["title"] if "title" in doc.keys() else "Document"
            body = doc["body"] if "body" in doc.keys() else ""
        elif isinstance(doc, dict):
            title = doc.get("title") or "Document"
            body = doc.get("body") or ""
        else:
            title = doc[1] if len(doc) > 1 else "Document"
            body = doc[2] if len(doc) > 2 else ""

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

        safe = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in (title or "Document")).strip() or "Document"
        path = filedialog.asksaveasfilename(
            title="Export Document",
            defaultextension=ext,
            initialfile=f"{safe}{ext}",
            filetypes=filetypes,
        )
        if not path:
            return

        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            if isinstance(body, (bytes, bytearray)) and ext not in (".txt", ".opml", ".html", ".svg", ".xml"):
                Path(path).write_bytes(bytes(body))
            else:
                if isinstance(body, (bytes, bytearray)):
                    try:
                        text_out = body.decode("utf-8")
                    except Exception:
                        try:
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

    # ---------------- Base64 image helpers ----------------

    def _looks_like_base64(self, s: str) -> bool:
        s = s.strip()
        if s.lower().startswith("data:image/") and ";base64," in s:
            return True
        if not s or any(c in s for c in "<>{}[]\\\"'"):
            return False
        import re as _re
        s_nows = _re.sub(r"\s+", "", s)
        if len(s_nows) < 16 or (len(s_nows) % 4) != 0:
            return False
        return _re.fullmatch(r"[A-Za-z0-9+/=]+", s_nows) is not None

    def _try_decode_image_base64(self, data: str | bytes) -> bytes | None:
        import base64, re as _re
        if isinstance(data, (bytes, bytearray)):
            try:
                data = data.decode("utf-8", errors="strict")
            except Exception:
                return None
        s = data.strip()
        if s.lower().startswith("data:image/") and ";base64," in s:
            b64 = s.split(",", 1)[1]
            try:
                return base64.b64decode(b64, validate=True)
            except Exception:
                return None
        if self._looks_like_base64(s):
            try:
                s_nows = _re.sub(r"\s+", "", s)
                return base64.b64decode(s_nows, validate=True)
            except Exception:
                return None
        return None

    def _is_image_bytes(self, b: bytes) -> bool:
        if b.startswith(b"\x89PNG\r\n\x1a\n"): return True
        if b.startswith(b"\xff\xd8\xff"): return True  # JPEG
        if b[:6] in (b"GIF87a", b"GIF89a"): return True
        if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP": return True
        if b[:2] == b"BM": return True  # BMP
        return False

    def _maybe_render_image_doc(self, title: str | None, body) -> bool:
        """Try to recognize and render an image stored as base64 or binary. Return True if rendered."""
        # If title suggests image, try direct/b64 forms
        if isinstance(title, str) and self._looks_like_image(title):
            if isinstance(body, (bytes, bytearray)) and self._is_image_bytes(bytes(body)):
                self._hide_opml(); self.text.delete("1.0", tk.END)
                self._show_image_bytes(bytes(body)); return True
            if isinstance(body, str):
                blob = self._try_decode_image_base64(body)
                if blob and self._is_image_bytes(blob):
                    self._hide_opml(); self.text.delete("1.0", tk.END)
                    self._show_image_bytes(blob); return True
            if isinstance(body, (bytes, bytearray)):
                blob = self._try_decode_image_base64(body)
                if blob and self._is_image_bytes(blob):
                    self._hide_opml(); self.text.delete("1.0", tk.END)
                    self._show_image_bytes(blob); return True

        # Otherwise inspect body first
        if isinstance(body, (bytes, bytearray)):
            b = bytes(body)
            if self._is_image_bytes(b):
                self._hide_opml(); self.text.delete("1.0", tk.END)
                self._show_image_bytes(b); return True
            blob = self._try_decode_image_base64(b)
            if blob and self._is_image_bytes(blob):
                self._hide_opml(); self.text.delete("1.0", tk.END)
                self._show_image_bytes(blob); return True

        if isinstance(body, str):
            blob = self._try_decode_image_base64(body)
            if blob and self._is_image_bytes(blob):
                self._hide_opml(); self.text.delete("1.0", tk.END)
                self._show_image_bytes(blob); return True

        return False

    # ---------------- Rendering ----------------

    def _render_document(self, doc):
        """Render a document once, parse green links, auto-render OPML, and decode images (base64/binary)."""
        # Always clear any previous image so it doesn't persist across docs
        self._hide_image()
        self._last_pil_img = None
        self._last_tk_img = None

        # Normalize fields
        if isinstance(doc, dict):
            title = doc.get("title")
            body = doc.get("body")
        elif hasattr(doc, "__iter__"):
            title = doc[1] if len(doc) > 1 else None
            body = doc[2] if len(doc) > 2 else ""
        else:
            title, body = None, str(doc)

        # 1) OPML?
        if isinstance(body, str):
            b_norm = body.lstrip("\ufeff\r\n\t ")
            if "<opml" in b_norm.lower():
                self._render_opml_from_string(b_norm)
                return

        # 2) Image? (base64 or binary)
        if self._maybe_render_image_doc(title, body):
            return

        
        # 2.5) Inline base64 images (image_render)
        if isinstance(body, str):
            try:
                blobs = image_render.extract_image_bytes_all(body)
            except Exception:
                blobs = []
            if blobs:
                self._hide_opml()
                # Render images centered inside the Text widget; keep the image pane clear to avoid duplication
                if image_render.show_images_in_text(self.text, blobs):
                    if hasattr(self, 'img_label'):
                        try: self.img_label.configure(image="")
                        except Exception: pass
                    return
# 3) Fallbacks: show as text (avoid giant blobs)
        self._hide_opml()
        self.text.delete("1.0", tk.END)

        if isinstance(body, (bytes, bytearray)):
            self.text.insert(tk.END, "[binary document]")
            return

        if isinstance(body, str) and len(body) > 200_000:
            self.text.insert(tk.END, "[large binary-like document]")
            return

        self.text.insert(tk.END, body or "")
        hypertext_parser.parse_links(self.text, body or "", self._on_link_click)

    def _on_link_click(self, doc_id):
        if self.current_doc_id is not None:
            self.history.append(self.current_doc_id)
        # clear any previous image before loading the new doc
        self._hide_image()
        self._last_pil_img = None
        self._last_tk_img = None

        self.current_doc_id = doc_id
        doc = self.doc_store.get_document(doc_id)
        if doc:
            self._render_document(doc)

    def _on_delete_clicked(self):
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

    def _sniff_image_bytes(self, b):
        """Return image MIME type if bytes match a known format, else None."""
        if not isinstance(b, (bytes, bytearray)):
            return None
        hdr = bytes(b[:12])
        if hdr.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
        if hdr.startswith(b"\xff\xd8"): return "image/jpeg"
        if hdr.startswith(b"GIF87a") or hdr.startswith(b"GIF89a"): return "image/gif"
        if hdr.startswith(b"BM"): return "image/bmp"
        if len(hdr) >= 12 and hdr[0:4] == b"RIFF" and hdr[8:12] == b"WEBP": return "image/webp"
        return None

    def _filetypes_images_first(self):
        return [
            ("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
            ("Text files", "*.txt *.md *.opml *.xml *.html *.htm *.json"),
            ("All files", "*.*"),
        ]

    def _data_url_from_path(self, path):
        from pathlib import Path
        p = Path(path)
        b = p.read_bytes()
        import mimetypes
        mt, _ = mimetypes.guess_type(p.name)
        if not mt or not mt.startswith("image/"):
            if b.startswith(b"\x89PNG\r\n\x1a\n"):
                mt = "image/png"
            elif b.startswith(b"\xff\xd8"):
                mt = "image/jpeg"
            elif b.startswith(b"GIF87a") or b.startswith(b"GIF89a"):
                mt = "image/gif"
            elif b.startswith(b"BM"):
                mt = "image/bmp"
            elif len(b) >= 12 and b[0:4] == b"RIFF" and b[8:12] == b"WEBP":
                mt = "image/webp"
            else:
                mt = "application/octet-stream"
        import base64
        return "data:" + mt + ";base64," + base64.b64encode(b).decode("ascii")

    def _export_current_images_aware(self, event=None):
        """Export current doc; if body is data:image;base64, write real bytes."""
        body = None
        try:
            if hasattr(self, "get_current_body") and callable(getattr(self, "get_current_body")):
                body = self.get_current_body()
            elif hasattr(self, "text"):
                body = self.text.get("1.0", "end-1c")
        except Exception:
            body = None
        if not isinstance(body, str) or not body.startswith("data:image/"):
            if hasattr(self, "_on_export_clicked"):
                try:
                    return self._on_export_clicked()
                except Exception:
                    pass
            return
        import re, base64
        m = re.match(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.*)$", body, re.S)
        if not m:
            if hasattr(self, "_on_export_clicked"):
                try:
                    return self._on_export_clicked()
                except Exception:
                    pass
            return
        mime, b64 = m.groups()
        extmap = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/bmp": ".bmp", "image/webp": ".webp"}
        ext = extmap.get(mime, ".bin")
        from tkinter import filedialog, messagebox
        fn = filedialog.asksaveasfilename(defaultextension=ext, filetypes=[("All files", "*.*")])
        if not fn:
            return
        try:
            with open(fn, "wb") as f:
                f.write(base64.b64decode(b64))
            try:
                messagebox.showinfo("Export", "Saved: " + str(fn))
            except Exception:
                pass
        except Exception:
            pass

    def _on_import_images_clicked(self, event=None):
        from tkinter import filedialog, messagebox
        paths = filedialog.askopenfilenames(
            title="Import Images...",
            filetypes=self._filetypes_images_first()
        )
        if not paths:
            return
        created = []
        for path in paths:
            try:
                body = self._data_url_from_path(path)
                try:
                    from pathlib import Path as _P
                    title = _P(path).name
                except Exception:
                    title = "image"
                doc_id = None
                # GUI helpers
                for name in ("create_document","new_document","add_document_here"):
                    fn = getattr(self, name, None)
                    if callable(fn):
                        try:
                            doc_id = fn(title, body); break
                        except TypeError:
                            try:
                                doc_id = fn({'title': title, 'body': body}); break
                            except Exception:
                                pass
                if doc_id is None:
                    try:
                        from modules import document_store as _ds
                        for name in ("create_document","add_document","insert_document","new_document","create","add"):
                            fn = getattr(_ds, name, None)
                            if callable(fn):
                                try:
                                    doc_id = fn(title, body); break
                                except TypeError:
                                    try:
                                        doc_id = fn({'title': title, 'body': body}); break
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                if doc_id is not None:
                    created.append(doc_id)
            except Exception:
                continue
        if created:
            last_id = created[-1]
            try:
                messagebox.showinfo("Import", "Document " + str(last_id) + " created")
            except Exception:
                pass
            try:
                if hasattr(self, "reload_index"):
                    self.reload_index()
                tree = getattr(self, "tree", None)
                if tree:
                    for it in tree.get_children(""):
                        vals = tree.item(it, "values")
                        if vals and str(vals[0]) == str(last_id):
                            tree.selection_set(it); tree.see(it)
                            if hasattr(self, "open_doc_by_id"):
                                self.open_doc_by_id(last_id)
                            break
            except Exception:
                pass




def sanitize_doc(doc):
    if isinstance(doc["body"], bytes):
        try:
            doc["body"] = doc["body"].decode("utf-8")
        except UnicodeDecodeError:
            doc["body"] = doc["body"].decode("utf-8", errors="replace")
    return doc

def _sniff_image_bytes(self, b: bytes) -> str | None:


    if b.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"


    if b.startswith(b"\xff\xd8"): return "image/jpeg"


    if b.startswith(b"GIF87a") or b.startswith(b"GIF89a"): return "image/gif"


    if b.startswith(b"BM"): return "image/bmp"


    if len(b) >= 12 and b[0:4] == b"RIFF" and b[8:12] == b"WEBP": return "image/webp"


    return None



    def _sniff_image_bytes(self, b):


        """Return image MIME type if bytes match a known format, else None."""


        if not isinstance(b, (bytes, bytearray)):


            return None


        hdr = bytes(b[:12])


        if hdr.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"


        if hdr.startswith(b"\xff\xd8"): return "image/jpeg"


        if hdr.startswith(b"GIF87a") or hdr.startswith(b"GIF89a"): return "image/gif"


        if hdr.startswith(b"BM"): return "image/bmp"


        if len(hdr) >= 12 and hdr[0:4] == b"RIFF" and hdr[8:12] == b"WEBP": return "image/webp"


        return None


# --- FunKit: inline webpane (tkinterweb) ---
def _ensure_webpane(self):
    """
    Create/reuse an inline HTML viewer backed by tkinterweb.HtmlFrame
    inside the document/content area. Returns the HtmlFrame or None.
    """
    try:
        if getattr(self, "_webpane", None):
            return self._webpane

        # Try a few likely container attributes used in FunKit/DemoKit
        container = None
        for name in (
            "document_pane", "doc_container", "document_frame",
            "right_pane", "content_frame", "main_right", "body"
        ):
            container = getattr(self, name, None)
            if container is not None:
                break

        # Fall back to 'self' if no specific pane is exposed
        if container is None:
            container = self

        from tkinterweb import HtmlFrame  # pip install tkinterweb
        frame = HtmlFrame(container, messages_enabled=False)
        # Try to replace/overlay in the pane; pack is used in most builds
        try:
            frame.pack(fill="both", expand=True)
        except Exception:
            pass

        self._webpane = frame
        return frame
    except Exception as _e:
        import logging; logging.warning("Inline webpane unavailable: %s", _e)
        return None

def _render_url_in_pane(self, url: str):
    """
    Try to display a URL inside the app's document pane.
    Raises RuntimeError if we can't render inline.
    """
    import logging
    frame = _ensure_webpane(self)
    if frame is None:
        raise RuntimeError("inline webpane not available")
    try:
        # HtmlFrame API supports .load_website for remote URLs
        frame.load_website(url)
        logging.info("Inline webpane: loaded %s", url)
        return True
    except Exception as e:
        logging.exception("Inline webpane failed for %s: %s", url, e)
        raise
# ------------------------------------------------------------------


# --- FunKit: strong inline webpane ---
def _get_doc_container(self):
    """
    Prefer the parent of the main document Text widget so the web view
    appears exactly where the document content normally lives.
    """
    cand = getattr(self, "document_text", None)
    if cand is not None and hasattr(cand, "master"):
        return cand.master
    for name in ("document_pane","doc_container","document_frame","right_pane","content_frame","main_right","body"):
        obj = getattr(self, name, None)
        if obj is not None:
            return obj
    return self  # last resort

def _ensure_webpane(self):
    """
    Create (or reuse) a tkinterweb.HtmlFrame inside the document container.
    If a text-based doc widget exists, hide it while the webpane is visible.
    """
    import logging
    try:
        # Reuse if already present
        pane = getattr(self, "_webpane", None)
        if pane: 
            try:
                # make sure it's mapped
                if hasattr(pane, "pack"):
                    pane.pack(fill="both", expand=True)
            except Exception:
                pass
            # hide text view if present
            txt = getattr(self, "document_text", None)
            if txt and hasattr(txt, "pack_forget"):
                try: txt.pack_forget()
                except Exception: pass
            return pane

        container = _get_doc_container(self)
        # Hide the text document widget if present
        txt = getattr(self, "document_text", None)
        if txt and hasattr(txt, "pack_forget"):
            try: txt.pack_forget()
            except Exception: pass

        from tkinterweb import HtmlFrame  # pip install tkinterweb
        pane = HtmlFrame(container, messages_enabled=False)
        try:
            pane.pack(fill="both", expand=True)
        except Exception:
            pass
        self._webpane = pane
        logging.info("Inline webpane created in %r", container)
        return pane
    except Exception as e:
        import logging
        logging.warning("Inline webpane unavailable: %s", e)
        return None

def _show_url_in_pane(self, url: str) -> bool:
    """
    Try to display URL inline. Returns True if shown inline, False otherwise.
    """
    import logging
    pane = _ensure_webpane(self)
    if pane is None:
        logging.info("Inline webpane not available; cannot show %s inline", url)
        return False
    try:
        # HtmlFrame API
        pane.load_website(url)
        logging.info("Inline webpane loaded %s", url)
        return True
    except Exception as e:
        logging.exception("Inline webpane failed for %s: %s", url, e)
        return False
# ------------------------------------------------------------------


# --- FunKit: Qt6 web renderer fallback ---
def _render_with_qt6(self, url: str):
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QUrl
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        import multiprocessing as _mp
        def _qt_proc(u: str):
            app = QApplication([])
            v = QWebEngineView()
            v.setUrl(QUrl(u))
            v.resize(1024, 768)
            v.setWindowTitle("FunKit Web View")
            v.show()
            app.exec()
        p = _mp.Process(target=_qt_proc, args=(url,), daemon=False)
        p.start()
    except Exception as e:
        import webbrowser, logging
        logging.warning("QT6 unavailable or failed (%s); opening system browser.", e)
        (
            self._show_url_in_pane(url)
            or (hasattr(self, "_render_with_qt6") and (self._render_with_qt6(url) or True))
            or webbrowser.open(url)
        )

