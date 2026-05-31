# modules/opml_crawler_adapter.py
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Callable, Tuple, List, Set, Optional
from urllib.parse import urljoin

# Try requests; fall back to urllib if unavailable
try:
    import requests
    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    import urllib.request  # type: ignore
    _HAVE_REQUESTS = False


DEFAULT_HEADERS = {
    "User-Agent": "PiKit-OPML-Crawler/1.0 (+pikit)",
    "Accept": "text/xml, application/xml, text/html, */*",
}


def _fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch URL and return decoded text (utf-8 with replace)."""
    try:
        if _HAVE_REQUESTS:
            r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            r.raise_for_status()
            # Some servers mislabel content-type; we still read text as-is.
            return r.text
        else:
            req = urllib.request.Request(url, headers=DEFAULT_HEADERS)  # type: ignore[attr-defined]
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # type: ignore[attr-defined]
                data = resp.read()
            return data.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[opml_crawler] fetch failed {url}: {e}")
        return None


def _load_local(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        print(f"[opml_crawler] read failed {path}: {e}")
        return None


def _is_opml(text: str) -> bool:
    """Cheap OPML check: parse root and verify <opml>."""
    if not text:
        return False
    try:
        root = ET.fromstring(text)
        return (root.tag or "").lower().endswith("opml")
    except ET.ParseError:
        return False


def _iter_opml_links_from_xml(xml_text: str, base_url: Optional[str] = None) -> List[str]:
    """
    Extract likely OPML links from <outline> elements:
      - xmlUrl="<url>"
      - url="<url>" (when it ends with .opml)
      - type="link" with url ending in .opml
    """
    links: List[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"[opml_crawler] parse error: {e}")
        return links

    for el in root.findall(".//outline"):
        attrs = el.attrib
        url = attrs.get("xmlUrl") or attrs.get("url")
        typ = (attrs.get("type") or "").lower()
        if not url:
            continue
        url_l = url.lower()
        if url_l.endswith(".opml") or (typ == "link" and url_l.endswith(".opml")):
            links.append(urljoin(base_url, url) if base_url else url)
    return links


def _iter_opml_links_from_html(html_text: str, base_url: Optional[str] = None) -> List[str]:
    """
    Very small, dependency-free extractor:
    find href="...opml" and resolve relative links.
    """
    links: List[str] = []
    for m in re.finditer(r'href\s*=\s*["\']([^"\']+?\.opml)([#?"\']|$)', html_text, flags=re.IGNORECASE):
        url = m.group(1)
        links.append(urljoin(base_url, url) if base_url else url)
    return links


def crawl_opml(
    start: str,
    max_depth: int = 3,
    visited: Optional[Set[str]] = None,
) -> List[Tuple[str, str]]:
    """
    Crawl an entry point (URL or local file) and gather text payloads.
    Returns a flat list of (source, payload_text).

    Notes:
      - If the payload is OPML, we recurse into OPML links inside it.
      - If the payload is HTML, we ALSO recurse into any .opml links found in the HTML.
      - This function does NOT write to the database and does NOT convert to OPML.
        Let the GUI/CLI call aopmlengine.convert_payload_to_opml(...) on each payload.
    """
    if visited is None:
        visited = set()

    key = start.strip()
    if key in visited:
        return []
    visited.add(key)

    # Load text
    if key.startswith(("http://", "https://")):
        payload = _fetch_url(key)
        base_url = key
    else:
        payload = _load_local(key)
        base_url = None

    if not payload:
        return []

    results: List[Tuple[str, str]] = [(key, payload)]

    if max_depth <= 0:
        return results

    # Recurse based on what we have
    if _is_opml(payload):
        children = _iter_opml_links_from_xml(payload, base_url)
    else:
        children = _iter_opml_links_from_html(payload, base_url)

    for child_url in children:
        if child_url in visited:
            continue
        results.extend(crawl_opml(child_url, max_depth=max_depth - 1, visited=visited))

    return results


def crawl_and_import(
    start: str,
    import_fn: Callable[[str, str], None],
    max_depth: int = 3,
) -> List[Tuple[str, str]]:
    """
    Crawl and invoke `import_fn(source, payload_text)` for each gathered item.
    WARNING: If you use this from a GUI thread, schedule the DB writes on the Tk thread
    (e.g., via `self.after(0, ...)`) to avoid sqlite cross-thread errors.
    """
    gathered = crawl_opml(start, max_depth=max_depth)
    for src, payload_text in gathered:
        try:
            import_fn(src, payload_text)
        except Exception as e:
            print(f"[opml_crawler] import failed for {src}: {e}")
    return gathered

