"""
Minimal OPML/nav helpers to satisfy gui_tkinter imports.
Fill in real logic later; these are safe no-ops with basic URL handling.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple

_HTTP_RE = re.compile(r'^(https?://|file://|about:blank|data:)')

def is_url(text: str) -> bool:
    return bool(text) and bool(_HTTP_RE.match(text.strip()))

def normalize_url(text: str) -> str:
    t = (text or "").strip()
    if t and not _HTTP_RE.match(t):
        return "http://" + t
    return t

def extract_links_from_opml(opml_text: str) -> List[Tuple[str, str]]:
    # very lightweight scan: looks for xml attributes like xmlUrl= / htmlUrl=
    links: List[Tuple[str, str]] = []
    if not opml_text:
        return links
    for m in re.finditer(r'(xmlUrl|htmlUrl|url)\s*=\s*"([^"]+)"', opml_text):
        kind, url = m.group(1), m.group(2)
        links.append((kind, url))
    return links

def outline_from_opml(opml_text: str) -> Dict[str, Any]:
    # placeholder structure used by some callers; return minimal tree
    return {"type": "opml", "links": extract_links_from_opml(opml_text)}

def open_or_normalize_target(target: str) -> str:
    # returns a safe URL-ish string for the webview loader
    return normalize_url(target)

# Compatibility shims some UIs expect:

def maybe_handle_nav(text: str) -> Optional[str]:
    """
    If text looks like a URL, return a normalized URL to load.
    Otherwise return None so caller can treat it as a search/doc id/etc.
    """
    t = normalize_url(text)
    return t if is_url(t) else None

def build_sidebar_items(opml_text: str) -> List[Dict[str, str]]:
    """
    Return simple items for a sidebar/tree; callers can iterate safely.
    """
    items: List[Dict[str, str]] = []
    for kind, url in extract_links_from_opml(opml_text):
        items.append({"title": url, "kind": kind, "url": url})
    return items

def is_opml(text: str) -> bool:
    return isinstance(text, str) and "<opml" in text.lower()
