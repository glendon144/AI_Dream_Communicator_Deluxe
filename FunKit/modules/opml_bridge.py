# modules/opml_bridge.py
"""
Bridge layer between FunKit and PiKit's OPML engine/extras.
- Dynamically adapts to function names exported by opml_extras_plugin.
- Falls back to a stdlib-based heading parser when aopml_engine does not
  expose html_to_outline / outline_to_html (used only for preview).
"""

import os
import tempfile
import webbrowser
import logging
import importlib
from typing import Optional, Dict, Any, List, Callable

log = logging.getLogger(__name__)

# --------------------------------------------------------------------
# Small outline node and fallback HTML<->outline helpers
# --------------------------------------------------------------------

class _OutlineNode:
    __slots__ = ("text", "children")
    def __init__(self, text: str):
        self.text = text
        self.children: List["_OutlineNode"] = []

def _fallback_html_to_outline(html: str) -> _OutlineNode:
    """Minimal heading parser: builds an outline from <h1>.. <h6>."""
    from html.parser import HTMLParser
    import re

    class _HParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.root = _OutlineNode("Document")
            self.stack: List[tuple[int, _OutlineNode]] = [(0, self.root)]
            self._curr_level: Optional[int] = None
            self._buf: List[str] = []

        def handle_starttag(self, tag, attrs):
            if tag and len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
                lvl = int(tag[1])
                if 1 <= lvl <= 6:
                    self._curr_level = lvl
                    self._buf.clear()

        def handle_data(self, data):
            if self._curr_level is not None:
                self._buf.append(data)

        def handle_endtag(self, tag):
            if self._curr_level is not None and tag == f"h{self._curr_level}":
                txt = re.sub(r"\s+", " ", "".join(self._buf).strip())
                if txt:
                    node = _OutlineNode(txt)
                    # Pop until parent level < current level
                    while self.stack and self.stack[-1][0] >= self._curr_level:
                        self.stack.pop()
                    self.stack[-1][1].children.append(node)
                    self.stack.append((self._curr_level, node))
                self._curr_level = None
                self._buf.clear()

    p = _HParser()
    p.feed(html or "")
    return p.root

def _fallback_outline_to_html(root: _OutlineNode) -> str:
    """Render a very simple nested HTML list from an outline tree."""
    def _render(node: _OutlineNode) -> str:
        if not node.children:
            return ""
        parts = ["<ul>"]
        for ch in node.children:
            parts.append(f"<li>{_esc(ch.text)}{_render(ch)}</li>")
        parts.append("</ul>")
        return "".join(parts)

    def _esc(s: str) -> str:
        import html
        return html.escape(s, quote=True)

    body = _render(root)
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<style>body{font:14px/1.45 system-ui,Segoe UI,Roboto,Helvetica,Arial}"
        "ul{margin:0.3rem 0 0.3rem 1.2rem}li{margin:0.15rem 0}</style>"
        "<body>"
        "<h1>Outline Preview</h1>"
        f"{body}"
        "</body>"
    )

# --------------------------------------------------------------------
# Import helpers
# --------------------------------------------------------------------

def _import(name: str):
    return importlib.import_module(name)

def _resolve_fn(mod, candidates: List[str]) -> Optional[Callable]:
    for n in candidates:
        fn = getattr(mod, n, None)
        if callable(fn):
            return fn
    return None


def _extract_document_text(record) -> str:
    if record is None:
        return ""
    try:
        if hasattr(record, "keys"):
            keys = set(record.keys())
            if "content" in keys and record["content"] is not None:
                return str(record["content"])
            if "body" in keys and record["body"] is not None:
                return str(record["body"])
            if "text" in keys and record["text"] is not None:
                return str(record["text"])
    except Exception:
        pass
    if isinstance(record, dict):
        return str(record.get("content") or record.get("body") or record.get("text") or "")
    try:
        if not isinstance(record, (str, bytes, bytearray)) and hasattr(record, "__getitem__"):
            return str(record[2] if len(record) > 2 else "")
    except Exception:
        pass
    return str(record or "")

# --------------------------------------------------------------------
# Try to load PiKit modules
# --------------------------------------------------------------------

try:
    _oxp = _import("modules.pikit_port.opml_extras_plugin")
except ImportError as e:
    raise ImportError("Could not import PiKit opml_extras_plugin") from e

try:
    _aeng = _import("modules.pikit_port.aopml_engine")
except ImportError:
    _aeng = None  # we'll rely on fallbacks

# Resolve OPML extras (export/import/install) with multiple candidates
_export_fn = _resolve_fn(
    _oxp,
    ["export_doc_to_opml", "export_to_opml", "doc_to_opml", "save_opml", "write_opml"],
)
_import_fn = _resolve_fn(
    _oxp,
    ["import_opml_to_docs", "import_opml", "load_opml", "import_from_opml"],
)
_install_fn = _resolve_fn(
    _oxp,
    ["install_opml_extras_into_app", "install_into_app", "install_opml_menu"],
)

# Resolve aopml_engine preview helpers (optional)
_html_to_outline = getattr(_aeng, "html_to_outline", None) if _aeng else None
_outline_to_html = getattr(_aeng, "outline_to_html", None) if _aeng else None

if not callable(_html_to_outline) or not callable(_outline_to_html):
    log.warning(
        "PiKit aopml_engine lacks html_to_outline/outline_to_html; "
        "using built-in fallback preview renderer."
    )
    # Bind fallbacks for preview only
    _html_to_outline = _fallback_html_to_outline
    _outline_to_html = _fallback_outline_to_html

# --------------------------------------------------------------------
# Public bridge functions (stable API for FunKit GUI)
# --------------------------------------------------------------------

def export_current_to_opml(doc_store, doc_id: int, out_path: Optional[str] = None) -> str:
    """Export a document from doc_store into an OPML file and return the path."""
    if doc_id is None:
        raise ValueError("No current document selected.")
    if not callable(_export_fn):
        raise ImportError("PiKit OPML exporter function not found in opml_extras_plugin.")
    try:
        return _export_fn(doc_store, doc_id, out_path=out_path)
    except TypeError:
        if out_path is not None:
            return _export_fn(doc_store, doc_id, out_path)
        return _export_fn(doc_store, doc_id)

def import_opml_file(doc_store, path: str) -> int:
    """Import an OPML file into doc_store, return the root/new doc id."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if not callable(_import_fn):
        raise ImportError("PiKit OPML importer function not found in opml_extras_plugin.")
    try:
        return _import_fn(doc_store, path)
    except TypeError:
        root_id = _import_fn(path)  # variant that returns a node/doc id
        attach = getattr(doc_store, "attach_imported_root", None)
        if callable(attach):
            root_id = attach(root_id)
        return root_id

def preview_outline_as_html(doc_store, doc_id: int) -> str:
    """
    Convert a document’s text into an outline and then into HTML.
    Returns the file path to the preview HTML file.
    """
    if doc_id is None:
        raise ValueError("No current document selected.")

    # Try common getters to extract raw text
    text = None
    for getter in ("get_document_text", "get_doc_text", "get_text", "get_content"):
        fn = getattr(doc_store, getter, None)
        if callable(fn):
            text = fn(doc_id)
            break
    if text is None:
        rec = getattr(doc_store, "get_document")(doc_id)
        text = _extract_document_text(rec)

    outline = _html_to_outline(text or "")
    html = _outline_to_html(outline)

    fd, path = tempfile.mkstemp(prefix="funkit_opml_preview_", suffix=".html")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info("Wrote OPML preview HTML -> %s", path)
    return path

def open_preview(path: str, open_fn=None):
    """
    Open an OPML preview either in the app’s own webview (if provided)
    or in the system default browser.
    """
    if callable(open_fn):
        try:
            return open_fn(path)
        except Exception:
            pass
    webbrowser.open(f"file://{path}", new=2)

def install_into_app_if_available(app):
    """
    Optional: call PiKit’s installer hook if it exists.
    """
    if callable(_install_fn):
        try:
            _install_fn(app)
            return True
        except Exception as e:
            log.warning("install_opml_extras_into_app failed: %s", e)
    return False
# Back-compat alias so existing code can keep calling the old name
def install_opml_extras_into_app(app):
    return install_into_app_if_available(app)
