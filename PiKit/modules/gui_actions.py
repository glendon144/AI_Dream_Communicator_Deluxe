import json
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox


def sanitize_doc(doc):
    """Normalize doc['body'] only for textual content."""
    if not isinstance(doc, dict):
        return doc
    body = doc.get("body")
    ctype = (doc.get("content_type") or "").lower()
    if isinstance(body, (bytes, bytearray)):
        if ctype.startswith("image/") or ctype in ("application/octet-stream",):
            return doc
        try:
            doc["body"] = body.decode("utf-8")
        except UnicodeDecodeError:
            doc["body"] = body.decode("latin-1", errors="replace")
    return doc


def import_doc(gui):
    path = filedialog.askopenfilename(title="Import", filetypes=[("Text", "*.txt"), ("All", "*.*")])
    if not path:
        return
    nid = gui.processor.import_document_from_path(path)
    gui.logger.info(f"Imported {nid}")
    gui._refresh_sidebar()
    doc = gui.doc_store.get_document(nid)
    if doc:
        gui._render_document(doc)


def export_doc(gui):
    if gui.current_doc_id is None:
        messagebox.showwarning("Export", "No document selected.")
        return
    path = filedialog.asksaveasfilename(title="Export Document", defaultextension=".txt")
    if not path:
        return
    gui.processor.export_document_to_path(gui.current_doc_id, path)
    messagebox.showinfo("Export", f"Saved to {path}")


def save_binary_as_text(gui):
    selected_item = gui.sidebar.selection()
    if not selected_item:
        return
    doc_id_str = gui.sidebar.item(selected_item, "values")[0]
    if not str(doc_id_str).isdigit():
        return
    doc_id = int(doc_id_str)
    gui.processor.save_binary_as_text(doc_id)
    doc = gui.doc_store.get_document(doc_id)
    if doc:
        gui._render_document(doc)


def import_directory(gui):
    dirpath = filedialog.askdirectory(title="Import Directory")
    if not dirpath:
        return
    gui.processor.import_directory(dirpath)
    gui._refresh_sidebar()


def open_opml_from_main(gui):
    path = filedialog.askopenfilename(title="Open OPML/XML", filetypes=[("OPML / XML", "*.opml *.xml"), ("All files", "*.*")])
    if not path:
        return
    try:
        new_id = gui.processor.import_opml_from_path(path)
    except Exception as e:
        messagebox.showerror("Open OPML", f"Failed to import:\n{e}")
        return
    gui._refresh_sidebar()
    gui.current_doc_id = new_id
    doc = gui.doc_store.get_document(new_id)
    if doc:
        gui._render_document(doc)
    if getattr(gui, "tree_win", None) and gui.tree_win.winfo_exists():
        try:
            gui.tree_win.load_opml_file(path)
            gui.tree_win.deiconify()
            gui.tree_win.lift()
            gui._apply_opml_expand_depth()
        except Exception:
            pass


def export_and_launch_server(gui):
    export_path = Path("exported_docs")
    export_path.mkdir(exist_ok=True)
    for doc in gui.doc_store.get_document_index():
        data = dict(gui.doc_store.get_document(doc["id"]))
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

