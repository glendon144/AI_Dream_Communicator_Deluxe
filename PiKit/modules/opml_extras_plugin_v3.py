"""
opml_extras_plugin_v3.py — OPML utilities (URL import, selection→OPML, batch convert)

Install (after creating the app in main.py):
    from modules.opml_extras_plugin_v3 import install_opml_extras_into_app
    install_opml_extras_into_app(app)

Features
- URL → OPML: accepts spaces, commas, semicolons, and newlines between URLs; auto-adds https:// if missing.
- Convert Selection → OPML: converts the current selection (or whole text doc if no selection) to OPML.
- Batch: Convert Selected → OPML: converts multiple sidebar-selected docs to OPML as new docs.
- Uses modules.aopmlengine if available; otherwise falls back to lightweight converters.
- Safe for sqlite3.Row/dict/tuple documents; UI updates happen on Tk main thread.
"""

from __future__ import annotations
import re
import threading
import urllib.request
import urllib.error

# Optional advanced engine
AOPML = None
try:
    from modules import aopmlengine as AOPML  # type: ignore
except Exception:
    AOPML = None  # type: ignore


# ----------------- Helpers -----------------

def _norm_row(row):
    """Normalize a document to (id, title, body). Supports sqlite3.Row/dict/tuple/list."""
    if row is None:
        return None, "Document", ""
    try:
        if hasattr(row, "keys"):
            rid = row["id"] if "id" in row.keys() else None
            title = row["title"] if "title" in row.keys() else "Document"
            body = row["body"] if "body" in row.keys() else ""
            return rid, title or "Document", body
    except Exception:
        pass
    if isinstance(row, dict):
        return row.get("id"), (row.get("title") or "Document"), row.get("body")
    try:
        if not isinstance(row, (str, bytes, bytearray)) and hasattr(row, "__getitem__"):
            rid = row[0] if len(row) > 0 else None
            title = row[1] if len(row) > 1 else "Document"
            body = row[2] if len(row) > 2 else ""
            return rid, title or "Document", body
    except Exception:
        pass
    return None, "Document", row


def _simple_text_to_opml(text: str, title: str = "Imported Text") -> str:
    """Lightweight text→OPML when AOPML is unavailable."""
    text = (text or "").strip()
    lines = [ln.strip() for ln in text.splitlines()]
    outlines = []
    for ln in lines:
        if not ln:
            continue
        txt = ln.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
        outlines.append(f'<outline text="{txt}"/>\n')
    body = "".join(outlines) or '<outline text="[empty]"/>\n'
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<opml version="2.0">\n'
        f'<head><title>{title}</title></head>\n'
        '<body>\n' + body + '</body>\n</opml>\n'
    )


def _simple_html_to_opml(html: str, title: str = "Imported HTML") -> str:
    """Minimal HTML→OPML using headings; used if AOPML is missing."""
    s = html or ""
    # collect headings in order of appearance
    pats = [
        (1, re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)),
        (2, re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)),
        (3, re.compile(r"<h3[^>]*>(.*?)</h3>", re.I | re.S)),
        (4, re.compile(r"<h4[^>]*>(.*?)</h4>", re.I | re.S)),
    ]
    items = []
    # Using finditer across the whole text for each heading level is simple and robust enough
    for level, pat in pats:
        for m in pat.finditer(s):
            txt = re.sub(r"<[^>]+>", "", m.group(1))
            txt = re.sub(r"\s+", " ", txt).strip()
            if txt:
                items.append((level, txt))
    if not items:
        # Fallback to paragraphs
        paras = re.split(r"</p>|<br\s*/?>", s, flags=re.I)
        items = [(3, re.sub(r"<[^>]+>", "", p).strip()) for p in paras if re.sub(r"<[^>]+>", "", p).strip()]
    # Build nested OPML by level
    out = [
        '<?xml version="1.0" encoding="utf-8"?>\n<opml version="2.0">\n',
        f'<head><title>{title}</title></head>\n<body>\n',
    ]
    stack = [0]
    for lvl, text in items:
        text_esc = text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
        while stack and lvl <= stack[-1]:
            out.append("</outline>\n")
            stack.pop()
        out.append(f'<outline text="{text_esc}">')
        stack.append(lvl)
    while len(stack) > 1:
        out.append("</outline>\n")
        stack.pop()
    if len(out) < 3:
        out.append('<outline text="[empty]"/>\n')
    out.append("</body>\n</opml>\n")
    return "".join(out)


def _to_opml(text_or_html: str, title: str = "Imported"):
    """Use AOPML if available; else heuristic to text/html converters."""
    if AOPML is not None:
        # Try module function
        fn = getattr(AOPML, "convert_text_or_html_to_opml", None)
        if callable(fn):
            try:
                return fn(text_or_html, title=title)
            except Exception:
                pass
        # Try class-based engine
        cls = getattr(AOPML, "AopmlEngine", None)
        if cls is not None:
            try:
                eng = cls()
                return eng.convert_text_or_html_to_opml(text_or_html, title=title)
            except Exception:
                pass
    low = (text_or_html or "").lower()
    if "<html" in low or "<body" in low or "<div" in low or "<p" in low:
        return _simple_html_to_opml(text_or_html, title)
    else:
        return _simple_text_to_opml(text_or_html, title)


def _fetch_url_text(url: str, timeout: float = 12.0) -> str:
    """Fetch URL and return decoded text with best-effort charset detection."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PiKit/1.0 (+URL->OPML)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ctype = resp.headers.get("Content-Type", "") or ""
        enc = "utf-8"
        m = re.search(r"charset=([\w\-\d]+)", ctype, re.I)
        if m:
            enc = m.group(1)
        try:
            return raw.decode(enc, errors="replace")
        except Exception:
            return raw.decode("utf-8", errors="replace")


def _parse_multi_input(s: str) -> list[str]:
    """Split user input into URLs on spaces/commas/semicolons/newlines and normalize."""
    tokens = re.split(r"[,\s;]+", (s or "").strip())
    out: list[str] = []
    for t in tokens:
        if not t:
            continue
        u = t.strip(' <>\"\'()[]')
        if not u:
            continue
        # Add scheme if missing
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", u):
            u = "https://" + u
        out.append(u)
    # de-dup while preserving order
    seen = set()
    uniq = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


# ----------------- Actions -----------------


def _action_import_url_as_opml(app):
    from tkinter import simpledialog as SD, messagebox as MB
    import threading, re

    urls_text = SD.askstring(
        "URL → OPML",
        "Enter URL(s) separated by spaces, commas, semicolons, or newlines:",
    )
    if not urls_text:
        return

    urls = _parse_multi_input(urls_text)
    if not urls:
        MB.showwarning("URL → OPML", "No valid URLs provided.")
        return

    # We will fetch/convert off-thread, then write to DB on the UI thread.
    prepared = []   # list of (url, title_guess, opml_text)
    fails = []      # list of (url, error)

    def worker():
        for u in urls:
            try:
                html = _fetch_url_text(u)
                title_guess = re.sub(r"^https?://(www\.)?", "", u).rstrip("/")
                opml = _to_opml(html, title=title_guess)
                prepared.append((u, title_guess, opml))
            except Exception as e:
                fails.append((u, str(e)))

        # Back to Tk thread: write to DB and update UI
        def write_and_finish():
            ok = []  # list of (url, new_id)
            for u, title_guess, opml in prepared:
                try:
                    nid = app.doc_store.add_document(title_guess, opml)
                    ok.append((u, nid))
                except Exception as e:
                    fails.append((u, str(e)))

            app._refresh_sidebar()
            if ok:
                last_id = ok[-1][1]
                app.current_doc_id = last_id
                doc = app.doc_store.get_document(last_id)
                if doc:
                    app._render_document(doc)

            msg = [f"Imported {len(ok)}; Failed {len(fails)}."]
            if fails:
                for u, err in fails[:5]:
                    msg.append(f" - {u} → {err}")
                if len(fails) > 5:
                    msg.append(f" ... and {len(fails) - 5} more.")
            MB.showinfo("URL → OPML", "\n".join(msg))

        app.after(0, write_and_finish)

    threading.Thread(target=worker, daemon=True).start()

    def _action_convert_selection_to_opml(app):

        from tkinter import messagebox as MB
        tk = __import__("tkinter")

        # Try selection from the text widget
        text = None
        try:
            start = app.text.index(tk.SEL_FIRST)
            end = app.text.index(tk.SEL_LAST)
            text = app.text.get(start, end)
        except Exception:
            text = None

        title = "OPML from Selection"
        if not text and getattr(app, "current_doc_id", None) is not None:
            row = app.doc_store.get_document(app.current_doc_id)
            _, title0, body = _norm_row(row)
            title = f"OPML for {title0}"
            if isinstance(body, (bytes, bytearray)):
                MB.showwarning("Convert → OPML", "Current document is binary; select text in the pane to convert.")
                return
            text = str(body or "")
        if not text:
            MB.showwarning("Convert → OPML", "Nothing to convert—select some text or open a text document.")
            return

        opml = _to_opml(text, title=title)
        nid = app.doc_store.add_document(title, opml)
        app._refresh_sidebar()
        app.current_doc_id = nid
        doc = app.doc_store.get_document(nid)
        if doc:
            app._render_document(doc)


def _action_batch_convert_selected_to_opml(app):
    from tkinter import messagebox as MB
    sel = getattr(app, "sidebar", None)
    if not sel:
        MB.showwarning("Batch Convert", "Sidebar not available for selection.")
        return
    items = sel.selection()
    if not items:
        MB.showwarning("Batch Convert", "Select one or more documents in the left list first.")
        return

    ids = []
    for iid in items:
        try:
            vals = sel.item(iid, "values")
            did = int(vals[0])
            ids.append(did)
        except Exception:
            continue

    if not ids:
        MB.showwarning("Batch Convert", "No valid document IDs in selection.")
        return

    results = {"ok": [], "skip": [], "fail": []}

    def worker():
        for did in ids:
            try:
                row = app.doc_store.get_document(did)
                _, title, body = _norm_row(row)
                if isinstance(body, (bytes, bytearray)):
                    results["skip"].append((did, "binary"))
                    continue
                text = str(body or "")
                if "<opml" in text.lower():
                    results["skip"].append((did, "already OPML"))
                    continue
                opml = _to_opml(text, title=f"OPML for {title}")
                nid = app.doc_store.add_document(f"OPML for {title}", opml)
                results["ok"].append((did, nid))
            except Exception as e:
                results["fail"].append((did, str(e)))

        def done():
            app._refresh_sidebar()
            msg = [
                f"Batch complete: {len(results['ok'])} converted, {len(results['skip'])} skipped, {len(results['fail'])} failed."
            ]
            if results["fail"]:
                for did, err in results["fail"][:5]:
                    msg.append(f" - id {did} → {err}")
                if len(results["fail"]) > 5:
                    msg.append(f" ... and {len(results['fail']) - 5} more.")
            MB.showinfo("Batch Convert → OPML", "\n".join(msg))

        app.after(0, done)

    threading.Thread(target=worker, daemon=True).start()


# ----------------- Install -----------------

def install_opml_extras_into_app(app):
    """Wire menu items, hotkeys, and (if present) toolbar buttons into the running app."""
    # Menu retrieval / creation
    menu = None
    try:
        menu = app.nametowidget(app.cget("menu"))
    except Exception:
        pass
    if menu is None:
        import tkinter as tk
        menu = tk.Menu(app)
        app.config(menu=menu)

    import tkinter as tk
    opml_menu = tk.Menu(menu, tearoff=0)
    opml_menu.add_command(label="URL → OPML…", command=lambda a=app: _action_import_url_as_opml(a))
    opml_menu.add_command(label="Convert Selection → OPML", command=lambda a=app: _action_convert_selection_to_opml(a))
    opml_menu.add_command(label="Batch: Convert Selected → OPML", command=lambda a=app: _action_batch_convert_selected_to_opml(a))
    menu.add_cascade(label="OPML", menu=opml_menu)

    # Hotkeys
    app.bind("<Control-u>", lambda e, a=app: _action_import_url_as_opml(a))
    app.bind("<Control-U>", lambda e, a=app: _action_import_url_as_opml(a))
    for seq in ("<Control-Shift-o>", "<Control-Alt-o>", "<F6>"):
        app.bind(seq, lambda e, a=app: _action_convert_selection_to_opml(a))
    app.bind("<Shift-F6>", lambda e, a=app: _action_batch_convert_selected_to_opml(a))

    # Optional toolbar buttons (if a toolbar frame exists)
    for attr in ("toolbar", "_toolbar", "toolbar_frame", "_toolbar_frame"):
        tb = getattr(app, attr, None)
        if tb:
            try:
                import tkinter.ttk as ttk
                ttk.Button(tb, text="URL → OPML", command=lambda a=app: _action_import_url_as_opml(a)).pack(side="left", padx=4)
                ttk.Button(tb, text="Convert → OPML", command=lambda a=app: _action_convert_selection_to_opml(a)).pack(side="left", padx=4)
                ttk.Button(tb, text="Batch → OPML", command=lambda a=app: _action_batch_convert_selected_to_opml(a)).pack(side="left", padx=4)
                break
            except Exception:
                pass
