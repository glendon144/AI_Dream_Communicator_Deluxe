"""
opml_extras_plugin_v2.py — Robust OPML extras for PiKit/DemoKit

Features restored/enhanced:
  • URL → OPML  (async fetch with timeouts; adds docs; opens the first)
  • Convert → OPML (uses selection if present from ANY Text widget, else whole doc)
UI integrations:
  • Adds toolbar buttons ("Convert → OPML", "URL → OPML") when possible
  • Adds a top-level "OPML" menu with the same actions
Hotkeys (several variants for reliability across platforms/WM):
  • Ctrl+U                → URL → OPML
  • Ctrl+Shift+O          → Convert → OPML
  • Ctrl+Alt+O            → Convert → OPML
  • F6                    → Convert → OPML

Install (in main.py, after creating the app):
    from modules.opml_extras_plugin_v2 import install_opml_extras_into_app
    install_opml_extras_into_app(app)
"""
from __future__ import annotations

def _resolve_engine():
    EngineConfig = None
    build_opml_from_html = None
    build_opml_from_text = None
    try:
        from modules.aopmlengine import EngineConfig as EC, build_opml_from_html as BOH, build_opml_from_text as BOT
        EngineConfig, build_opml_from_html, build_opml_from_text = EC, BOH, BOT
    except Exception:
        try:
            from modules.aopmlengine import EngineConfig as EC, build_opml_from_html as BOH, build_opml_from_text as BOT
            EngineConfig, build_opml_from_html, build_opml_from_text = EC, BOH, BOT
        except Exception:
            pass
    return EngineConfig, build_opml_from_html, build_opml_from_text

def _get_any_selection_text(app) -> str | None:
    """Try several common text widgets; fall back to widget with focus; return selected text or None."""
    import tkinter as tk
    candidates = []
    for name in ("_text", "text", "main_text", "editor", "body_text", "content_text"):
        w = getattr(app, name, None)
        if isinstance(w, tk.Text):
            candidates.append(w)
    try:
        f = app.focus_get()
        if isinstance(f, tk.Text) and f not in candidates:
            candidates.insert(0, f)
    except Exception:
        pass
    for w in candidates:
        try:
            sel = w.get("sel.first", "sel.last")
            sel = (sel or "").strip()
            if sel:
                return sel
        except Exception:
            continue
    return None

def _convert_current_to_opml(self):
    from tkinter import messagebox
    import re

    EC, BOH, BOT = _resolve_engine()
    if EC is None:
        messagebox.showerror("Convert → OPML", "aopmlengine.py not found or failed to import.")
        return

    if getattr(self, "current_doc_id", None) is None:
        messagebox.showwarning("Convert → OPML", "No document selected.")
        return
    doc = self.doc_store.get_document(self.current_doc_id)
    if not doc:
        messagebox.showerror("Convert → OPML", "Document not found.")
        return

    # get title/body (tuple or dict)
    if isinstance(doc, dict):
        title = doc.get("title") or "Document"
        body  = doc.get("body") or ""
    else:
        title = (doc[1] if len(doc) > 1 else "Document") or "Document"
        body  = (doc[2] if len(doc) > 2 else "")

    # Prefer selection (from any Text); else whole body
    content = _get_any_selection_text(self)
    if not content:
        if isinstance(body, (bytes, bytearray)):
            try:
                from modules.hypertext_parser import render_binary_as_text  # type: ignore
                content = render_binary_as_text(body, title)
            except Exception:
                try:
                    content = body.decode("utf-8", errors="replace")
                except Exception:
                    content = str(body)
        else:
            content = str(body or "")

    # Decide HTML vs Text
    low = content.lower()
    is_htmlish = ("<html" in low) or ("<body" in low) or ("<div" in low) or ("<h1" in low) or ("<p" in low)
    cfg = EC(enable_ai=False, title=f"{title} (OPML)", owner_name=None)
    try:
        opml_doc = BOH(content, cfg) if is_htmlish else BOT(content, cfg)
        xml = opml_doc.to_xml()
    except Exception as e:
        messagebox.showerror("Convert → OPML", f"Failed to build OPML:\n{e}")
        return

    # Save new doc and open
    try:
        new_id = self.doc_store.add_document(f"{title} (OPML)", xml)
        if hasattr(self, "_on_link_click"):
            self._on_link_click(new_id)
        else:
            self.current_doc_id = new_id
            if hasattr(self, "_render_document"):
                self._render_document(self.doc_store.get_document(new_id))
    except Exception as e:
        messagebox.showerror("Convert → OPML", f"DB error:\n{e}")

            
    urls_text = SD.askstring("URL → OPML", "Enter URL(s) separated by spaces, commas, or newlines:")
if not urls_text:
    return

import re
tokens = re.split(r'[,\s;]+', urls_text.strip())
urls = []
for t in tokens:
    if not t:
        continue
    u = t.strip(' <>\"\'()[]')
    # Add scheme if missing
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://', u):
        u = "https://" + u
    urls.append(u)

# de-dup while preserving order
urls = list(dict.fromkeys(urls))
if not urls:
    return

    def _import_url_as_opml(self):

    """Fetch one or more URLs and import as OPML document(s), async + safe timeouts."""
    from tkinter import simpledialog as SD, messagebox
    import threading, time, re

    EC, BOH, BOT = _resolve_engine()
    if EC is None:
        messagebox.showerror("URL → OPML", "aopmlengine.py not found or failed to import.")
        return

    urls_text = SD.askstring("URL → OPML", "Enter one or more URLs (newline-separated):")
    if not urls_text:
        return
    urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
    if not urls:
        return

    # Busy cursor + tiny cancel dialog
    try:
        self.config(cursor="watch"); self.update_idletasks()
    except Exception:
        pass
    self._cancel_url_import = False

    import tkinter as tk
    from tkinter import ttk
    dlg = tk.Toplevel(self)
    dlg.title("Fetching URLs…")
    dlg.geometry("360x120+60+60")
    dlg.transient(self); dlg.grab_set()
    tk.Label(dlg, text=f"Fetching {len(urls)} URL(s)…", anchor="w").pack(fill="x", padx=10, pady=(10,4))
    status = tk.StringVar(value="Working…")
    tk.Label(dlg, textvariable=status, anchor="w").pack(fill="x", padx=10)
    def _cancel():
        self._cancel_url_import = True
        status.set("Cancelling…")
        btn.config(state="disabled")
    btn = ttk.Button(dlg, text="Cancel", command=_cancel); btn.pack(pady=10)

    MAX_BYTES, CONNECT_TIMEOUT, READ_TIMEOUT, TOTAL_BUDGET = 600_000, 8, 8, 12

    def _decode_bytes(raw: bytes, fallback="utf-8") -> str:
        try:
            return raw.decode("utf-8")
        except Exception:
            try:
                import chardet  # type: ignore
                enc = chardet.detect(raw).get("encoding") or fallback
                return raw.decode(enc, errors="replace")
            except Exception:
                return raw.decode(fallback, errors="replace")

    def _fetch(url: str) -> str:
        start = time.monotonic()
        # requests first
        try:
            import requests  # type: ignore
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 PiKit/OPML",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "close",
            }
            with requests.get(url, headers=headers, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), stream=True, allow_redirects=True) as r:
                r.raise_for_status()
                ctype = (r.headers.get("Content-Type") or "").lower()
                if "text/html" not in ctype and "xml" not in ctype:
                    raise RuntimeError(f"Unsupported Content-Type: {ctype or 'unknown'}")
                raw = bytearray()
                for chunk in r.iter_content(chunk_size=65536):
                    if self._cancel_url_import:
                        raise RuntimeError("Cancelled")
                    if chunk:
                        raw.extend(chunk)
                    if len(raw) > MAX_BYTES or (time.monotonic() - start) > TOTAL_BUDGET:
                        break
            return _decode_bytes(bytes(raw))
        except Exception:
            pass
        # urllib fallback
        try:
            import urllib.request, socket
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(READ_TIMEOUT)
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 PiKit/OPML",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Connection": "close",
                })
                with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT) as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    if "text/html" not in ctype and "xml" not in ctype:
                        raise RuntimeError(f"Unsupported Content-Type: {ctype or 'unknown'}")
                    raw = bytearray()
                    while True:
                        if self._cancel_url_import:
                            raise RuntimeError("Cancelled")
                        if (time.monotonic() - start) > TOTAL_BUDGET:
                            break
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            break
            finally:
                socket.setdefaulttimeout(old_timeout)
            return _decode_bytes(bytes(raw))
        except Exception as e:
            raise RuntimeError(str(e))

    def work():
        created_payloads, failed = [], []
        for i, url in enumerate(urls, 1):
            if self._cancel_url_import:
                failed.append((url, "Cancelled")); break
            try:
                self.after(0, lambda i=i, url=url: status.set(f"[{i}/{len(urls)}] {url}"))
                html = _fetch(url)
                m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
                title = m.group(1).strip() if m else url
                title = re.sub(r"\s+", " ", title)
                opml_title = f"{title} (OPML)"
                cfg = EC(enable_ai=False, title=opml_title, owner_name=None)
                try:
                    opml_doc = BOH(html or "", cfg)
                    xml = opml_doc.to_xml()
                except Exception:
                    import re as _re
                    text_only = _re.sub(r"<[^>]+>", " ", html or "", flags=_re.S)
                    text_only = _re.sub(r"\s+", " ", text_only)
                    opml_doc = BOT(text_only[:MAX_BYTES], cfg)
                    xml = opml_doc.to_xml()
                created_payloads.append({"title": opml_title, "xml": xml})
            except Exception as e:
                failed.append((url, f"{e.__class__.__name__}: {e}"))

        def finish_on_ui():
            try:
                dlg.destroy()
            except Exception:
                pass
            try:
                self.config(cursor="")
            except Exception:
                pass
            created = []
            for payload in created_payloads:
                try:
                    nid = self.doc_store.add_document(payload["title"], payload["xml"])
                    created.append(nid)
                except Exception as e:
                    failed.append((payload["title"], f"DB: {e}"))
            self._refresh_sidebar()
            if created:
                try:
                    self._on_link_click(created[0])
                except Exception:
                    pass
            if failed:
                snippet = "; ".join(f"{u} → {err}" for u, err in failed[:3])
                extra = " (showing first 3)" if len(failed) > 3 else ""
                messagebox.showwarning("URL → OPML", f"Imported {len(created)}; {len(failed)} failed{extra}: {snippet}")
            else:
                messagebox.showinfo("URL → OPML", f"Imported {len(created)} OPML document(s).")

        self.after(0, finish_on_ui)

    import threading
    threading.Thread(target=work, daemon=True).start()

def attach_opml_extras_plugin(DemoKitGUI_cls):
    setattr(DemoKitGUI_cls, "_convert_current_to_opml", _convert_current_to_opml)
    setattr(DemoKitGUI_cls, "_import_url_as_opml", _import_url_as_opml)

def _add_toolbar_buttons(app) -> int:
    """Find a plausible toolbar and add buttons; returns count added."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return 0

    # Direct attributes some builds used
    for attr in ("toolbar", "_toolbar", "toolbar_frame", "_toolbar_frame"):
        parent = getattr(app, attr, None)
        if parent:
            try:
                btn1 = ttk.Button(parent, text="Convert → OPML", command=lambda a=app: a._convert_current_to_opml())
                btn1.pack(side="left", padx=2)
                btn2 = ttk.Button(parent, text="URL → OPML", command=lambda a=app: a._import_url_as_opml())
                btn2.pack(side="left", padx=2)
                return 2
            except Exception:
                pass

    # Heuristic: scan children for a Frame with a BACK or SAVE AS TEXT button
    target = None
    for w in app.winfo_children():
        try:
            kids = w.winfo_children()
        except Exception:
            continue
        score = 0
        for c in kids:
            try:
                t = c.cget("text")
                if isinstance(t, str) and t.strip().upper() in {"BACK", "SAVE AS TEXT", "CONVERT TO OPML", "URL → OPML", "URL -> OPML"}:
                    score += 1
            except Exception:
                pass
        if score >= 1:
            target = w; break

    if target:
        try:
            btn1 = ttk.Button(target, text="Convert → OPML", command=lambda a=app: a._convert_current_to_opml())
            btn1.pack(side="left", padx=2)
            btn2 = ttk.Button(target, text="URL → OPML", command=lambda a=app: a._import_url_as_opml())
            btn2.pack(side="left", padx=2)
            return 2
        except Exception:
            return 0
    return 0

def _ensure_opml_menu(app) -> int:
    """Add a dedicated 'OPML' menu with our actions; returns 1 if added/updated."""
    try:
        import tkinter as tk
    except Exception:
        return 0

    # Try to get the root menubar
    menubar = None
    try:
        menubar = app.nametowidget(app["menu"]) if app["menu"] else None
    except Exception:
        menubar = getattr(app, "menubar", None)

    if menubar is None:
        # Create a minimal menubar
        try:
            menubar = tk.Menu(app)
            app.config(menu=menubar)
        except Exception:
            return 0

    # Add or replace "OPML" cascade
    opml_menu = None
    # Try to find existing index
    try:
        end = menubar.index("end")
    except Exception:
        end = None
    if end is not None:
        for i in range(end + 1):
            try:
                if menubar.type(i) == "cascade" and menubar.entrycget(i, "label").strip().upper() == "OPML":
                    opml_menu = menubar.nametowidget(menubar.entrycget(i, "menu"))
                    break
            except Exception:
                continue
    if opml_menu is None:
        import tkinter as tk
        opml_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="OPML", menu=opml_menu)

    # Populate items (idempotent-ish: we clear first)
    try:
        opml_menu.delete(0, "end")
    except Exception:
        pass
    opml_menu.add_command(label="Convert → OPML\tCtrl+Shift+O / Ctrl+Alt+O / F6", command=lambda a=app: a._convert_current_to_opml())
    opml_menu.add_command(label="URL → OPML\tCtrl+U", command=lambda a=app: a._import_url_as_opml())
    return 1

def install_opml_extras_into_app(app) -> None:
    """Attach methods, add toolbar buttons and OPML menu, bind multiple hotkeys."""
    cls = app.__class__
    attach_opml_extras_plugin(cls)

    try:
        _add_toolbar_buttons(app)
    except Exception as e:
        print("[WARN] OPML extras: toolbar injection failed:", e)

    try:
        _ensure_opml_menu(app)
    except Exception as e:
        print("[WARN] OPML extras: menu injection failed:", e)

    # Multiple hotkeys for reliability
    try:
        app.bind_all("<Control-u>", lambda e: app._import_url_as_opml())
        for seq in ("<Control-Shift-o>", "<Control-Shift-O>", "<Control-Alt-o>", "<Control-Alt-O>", "<F6>"):
            app.bind_all(seq, lambda e, a=app: a._convert_current_to_opml())
    except Exception as e:
        print("[WARN] OPML extras: key bindings failed:", e)
