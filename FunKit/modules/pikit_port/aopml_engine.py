"""
aopml_engine.py — Aggressive OPML Engine for PiKit  # Changed filename reference

Given an input file (HTML or plain text), analyze and convert it into a
standards‑compliant OPML 2.0 document suitable for rendering in OPML readers.

Features
--------
- HTML parsing respects heading structure (<h1>.. <h6>) and list items.
- Plain text parsing infers section titles and breaks paragraphs into bullets
  when markers are detected; otherwise preserves the text as a single note.
- Optional AI assist: if `ai_interface.py` is available, the engine can
  offload hard‑to‑parse sections to AI (on a worker thread) and merge results.
- Zero external network usage unless `ai_interface` does so by design.

Intended to be included in a future PiKit release.

CLI
---
python aopml_engine.py INPUT_FILE [--title "Custom Title"] [--assume html|text]  # Updated script name
                      [--ai] [--out out.opml]

Notes
-----
- BeautifulSoup is used if available; otherwise the engine falls back to a
  minimalist HTML heading extractor using html.parser.
- The output is a *single* OPML document. Non‑hierarchical scraps are tucked
  under an "Unsorted" section.

Author: PiKit Team
License: MIT
"""
from __future__ import annotations

import os
import re
import io
import sys
import time
import json
import uuid
import types
import typing as t
import logging
from dataclasses import dataclass, field
from xml.sax.saxutils import escape as xml_escape

# --- Logging configuration -------------------------------------------------
logger = logging.getLogger("aopml_engine")  # Updated logger name
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

# --- Optional imports ------------------------------------------------------
try:
    from bs4 import BeautifulSoup  # type: ignore
    _HAVE_BS4 = True
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore
    _HAVE_BS4 = False

try:
    ai_interface = __import__("ai_interface")
    _HAVE_AI = True
except Exception:
    ai_interface = None
    _HAVE_AI = False

# --- OPML model ------------------------------------------------------------
@dataclass
class Outline:
    text: str
    children: list["Outline"] = field(default_factory=list)
    _attrs: dict[str, str] = field(default_factory=dict)

    def add(self, child: "Outline") -> None:
        self.children.append(child)

    def to_xml(self, indent: int = 2, level: int = 0) -> str:
        pad = " " * (indent * level)
        attrs = {"text": self.text}
        attrs.update(self._attrs)
        attr_str = " ".join(f"{k}=\"{xml_escape(v)}\"" for k, v in attrs.items())
        if not self.children:
            return f"{pad}<outline {attr_str}/>\n"
        s = io.StringIO()
        s.write(f"{pad}<outline {attr_str}>\n")
        for c in self.children:
            s.write(c.to_xml(indent, level + 1))
        s.write(f"{pad}</outline>\n")
        return s.getvalue()

@dataclass
class OPMLDocument:
    title: str
    date_created: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    owner_name: str | None = None
    outlines: list[Outline] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)

    def to_xml(self, indent: int = 2) -> str:
        head = io.StringIO()
        head.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
        head.write("<opml version=\"2.0\">\n")
        head.write("  <head>\n")
        head.write(f"    <title>{xml_escape(self.title)}</title>\n")
        head.write(f"    <dateCreated>{xml_escape(self.date_created)}</dateCreated>\n")
        head.write("    <generator>PiKit AOPML Engine</generator>\n")
        if self.owner_name:
            head.write(f"    <ownerName>{xml_escape(self.owner_name)}</ownerName>\n")
        # Additional metadata
        for k, v in self.meta.items():
            head.write(f"    <{k}>{xml_escape(v)}</{k}>\n")
        head.write("  </head>\n")
        head.write("  <body>\n")
        body = io.StringIO()
        for o in self.outlines:
            body.write(o.to_xml(indent=indent, level=1))
        tail = "  </body>\n</opml>\n"
        return head.getvalue() + body.getvalue() + tail

    def add(self, node: Outline) -> None:
        self.outlines.append(node)

# --- Heuristics ------------------------------------------------------------
_HTML_SIGNS = re.compile(r"<\s*(!doctype|html|head|body|h[1-6]|p|div|ul|ol|li)\b", re.I)
_LIST_MARK = re.compile(r"^\s*(?:[-*•‣·]|\d+[.)])\s+")
_TITLE_LINE = re.compile(r"^[\t ]*([A-Z][^a-z\n]{3,}|[#]{1,6}\s+.+)$")


def is_probably_html(text: str) -> bool:
    return bool(_HTML_SIGNS.search(text))


def split_paragraphs(text: str) -> list[str]:
    # Normalize newlines, keep paragraphs separated by blank lines
    parts = re.split(r"\n\s*\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def bulletize_lines(block: str) -> tuple[list[str] | None, str | None]:
    """Try to turn a block into bullets.
    Returns (bullets, remainder). If cannot bulletize, returns (None, original).
    """
    lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
    if not lines:
        return None, None
    if sum(bool(_LIST_MARK.match(ln)) for ln in lines) >= max(2, len(lines) // 2):
        bullets = [re.sub(_LIST_MARK, "", ln).strip() for ln in lines if _LIST_MARK.match(ln)]
        return bullets, None
    # Heuristic: colon‑delimited or semicolon list in a sentence
    if ":" in block and any(ch in block for ch in ";,•"):
        head, tail = block.split(":", 1)
        # split by semicolons or bullet symbols
        items = [it.strip(" \t-•‣·") for it in re.split(r"[;•\u2022\u25E6]|\s\-\s", tail) if it.strip()]
        if len(items) >= 2 and all(len(it) <= 240 for it in items):
            return items, head.strip()
    return None, block

# --- HTML parsing ----------------------------------------------------------
class _MiniHTMLHeadingParser:
    """Fallback HTML heading extractor using the standard library."""

    def __init__(self, html: str):
        from html.parser import HTMLParser

        self.headings: list[tuple[int, str]] = []

        class HP(HTMLParser):
            def __init__(self, outer: "_MiniHTMLHeadingParser"):
                super().__init__(convert_charrefs=True)
                self.outer = outer
                self._in_h: int | None = None
                self._buf: list[str] = []

            def handle_starttag(self, tag: str, attrs):
                if tag and len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
                    lvl = int(tag[1])
                    if 1 <= lvl <= 6:
                        self._in_h = lvl
                        self._buf.clear()

            def handle_endtag(self, tag: str):
                if self._in_h and tag == f"h{self._in_h}":
                    text = "".join(self._buf).strip()
                    if text:
                        self.outer.headings.append((self._in_h, re.sub(r"\s+", " ", text)))
                    self._in_h = None
                    self._buf.clear()

    def to_outline(self) -> "Outline":
        """
        Convert the collected heading tuples [(level:int, text:str), ...]
        into a nested Outline tree.
        """
        root = Outline("Document")
        stack: list[tuple[int, Outline]] = [(0, root)]

        for lvl, text in self.headings:
            node = Outline(text)
            # Pop until parent has strictly lower level
            while stack and lvl <= stack[-1][0]:
                stack.pop()
            # Attach to current parent, then push this node
            stack[-1][1].children.append(node)
            stack.append((lvl, node))

        return root


def html_to_outline(html: str) -> Outline:
    if _HAVE_BS4:
        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.string or "").strip() if soup.title and soup.title.string else None
        root = Outline(title or "Document")
        stack: list[tuple[int, Outline]] = [(0, root)]
        body = soup.body or soup
        for el in body.descendants:
            if getattr(el, "name", None) and re.fullmatch(r"h[1-6]", el.name or "", re.I):
                lvl = int(el.name[1])
                text = el.get_text(" ", strip=True)
                node = Outline(text)
                while stack and lvl <= stack[-1][0]:
                    stack.pop()
                stack[-1][1].add(node)
                stack.append((lvl, node))
            elif getattr(el, "name", None) in {"ul", "ol"}:
                # attach list to the most recent heading
                if stack:
                    parent = stack[-1][1]
                    lst = Outline("List")
                    for li in el.find_all("li", recursive=False):
                        txt = li.get_text(" ", strip=True)
                        if txt:
                            lst.add(Outline(txt))
                    if lst.children:
                        parent.add(lst)
            # paragraphs not under any heading become Unsorted
        # Capture stray paragraphs at top level
        unsorted = Outline("Unsorted")
        for p in body.find_all("p", recursive=True):
            txt = p.get_text(" ", strip=True)
            if txt:
                unsorted.add(Outline(txt))
        if unsorted.children:
            root.add(unsorted)
        return root
    else:
        logger.debug("bs4 not available; using minimal parser")
        return _MiniHTMLHeadingParser(html).to_outline()

# --- Plain text parsing ----------------------------------------------------

def text_to_outline(text: str, assumed_title: str | None = None) -> Outline:
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Infer title: first underlined or ATX heading (# Title) or ALLCAPS line
    title: str | None = None
    for i, ln in enumerate(lines[:8]):
        if ln.strip().startswith("# "):
            title = ln.strip("# ").strip()
            lines = lines[i + 1 :]
            break
        if i + 1 < len(lines) and set(lines[i + 1].strip()) in ({"="}, {"-"}) and len(lines[i + 1].strip()) >= max(3, len(ln.strip()) // 2):
            title = ln.strip()
            lines = lines[i + 2 :]
            break
        if _TITLE_LINE.match(ln):
            title = ln.strip("# ").strip()
            lines = lines[i + 1 :]
            break
    title = title or assumed_title or "Document"
    root = Outline(title)

    # Group paragraphs
    text_body = "\n".join(lines)
    paras = split_paragraphs(text_body)
    for para in paras:
        bullets, remainder = bulletize_lines(para)
        if bullets is not None:
            # Heading + bullets
            head_text = remainder if remainder else para.split("\n", 1)[0][:60]
            section = Outline(head_text if head_text else "List")
            for b in bullets:
                section.add(Outline(b))
            root.add(section)
        else:
            root.add(Outline(para))
    return root

# --- AI assist -------------------------------------------------------------
@dataclass
class AITask:
    section_id: str
    original: str
    result_xml: str | None = None
    error: str | None = None


def _ai_worker(tasks: list[AITask]):  # pragma: no cover (side‑effectful)
    if not _HAVE_AI:
        return
    try:
        for tsk in tasks:
            try:
                # Expected contract: ai_interface.suggest_opml(text:str) -> OPML outline XML (string)
                if hasattr(ai_interface, "suggest_opml"):
                    tsk.result_xml = ai_interface.suggest_opml(tsk.original)
                elif hasattr(ai_interface, "process_text_to_opml"):
                    tsk.result_xml = ai_interface.process_text_to_opml(tsk.original)
                else:
                    tsk.error = "ai_interface lacks suggest_opml/process_text_to_opml"
            except Exception as e:  # noqa: BLE001
                tsk.error = f"AI error: {e}"
    except Exception as e:  # noqa: BLE001
        logger.error("AI worker failed: %s", e)


# --- Public API ------------------------------------------------------------

# ---- Engine config (single, top-level) ----
from dataclasses import dataclass

@dataclass
class EngineConfig:
    enable_ai: bool = False
    owner_name: str | None = None
    owner_email: str | None = None
    title: str | None = None


# ---- small helper: tolerate cfg as object/dict/str/None ----
def _cfg_get(cfg, key, default=""):
    if cfg is None:
        return default
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


# ---- central entry the plugin prefers ----
def convert_payload_to_opml(title: str, payload, cfg: EngineConfig | dict | None = None) -> str:
    """
    Main entry point used by opml_extras_plugin.
    Detects HTML vs text and routes accordingly.
    Returns XML text.
    """
    text = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload or "")
    low = text.lower()
    if ("<html" in low) or ("<body" in low) or ("<div" in low) or ("<p" in low):
        doc = build_opml_from_html(title, text, cfg=cfg)
    else:
        doc = build_opml_from_text(title, text, cfg=cfg)
    return doc.to_xml()  # assumes OPMLDocument has .to_xml()


# ---- robust HTML path ----
def build_opml_from_html(title: str, html: str, cfg: EngineConfig | dict | None = None):
    """
    Parse HTML → outline → OPMLDocument (no owner fields).
    """
    outline = html_to_outline(html)

    _cfg_title   = _cfg_get(cfg, "title", "")
    _final_title = (outline.text or _cfg_title or title or "Document")

    # OPMLDocument doesn’t accept owner_* → don’t pass them
    doc = OPMLDocument(title=_final_title)

    # Transfer structure if any; otherwise add a single node
    for child in getattr(outline, "children", []):
        doc.add(child)
    if not getattr(outline, "children", []):
        doc.add(Outline(outline.text or _final_title))

    return doc


# ---- robust TEXT path ----

def build_opml_from_text(title: str, text: str, cfg: EngineConfig | dict | None = None):
    """
    Parse plain text → outline → OPMLDocument (no owner fields).
    """
    outline = text_to_outline(text, assumed_title=_cfg_get(cfg, "title", None))

    _cfg_title   = _cfg_get(cfg, "title", "")
    _final_title = (outline.text or _cfg_title or title or "Document")

    # OPMLDocument doesn’t accept owner_* → don’t pass them
    doc = OPMLDocument(title=_final_title)

    for child in getattr(outline, "children", []):
        doc.add(child)
    if not getattr(outline, "children", []):
        doc.add(Outline(outline.text or _final_title))

    return doc


def build_opml_from_file(path: str, cfg: EngineConfig | None = None) -> OPMLDocument:
    cfg = cfg or EngineConfig()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        data = f.read()
    if is_probably_html(data):
        logger.info("Detected HTML input")
        return build_opml_from_html(data, cfg)
    else:
        logger.info("Detected TEXT input")
        return build_opml_from_text(data, cfg)


# --- CLI ------------------------------------------------------------------

def _parse_argv(argv: list[str]) -> dict:
    import argparse

    p = argparse.ArgumentParser(description="PiKit AOPML Engine — HTML/TEXT to OPML")
    p.add_argument("input", help="Input file path (HTML or text)")
    p.add_argument("--title", dest="title", default=None, help="Override OPML title")
    p.add_argument("--assume", choices=["html", "text"], help="Assume input type, bypass detection")
    p.add_argument("--ai", action="store_true", help="Enable AI assist if ai_interface is present")
    p.add_argument("--owner", default=None, help="Owner name for OPML head")
    p.add_argument("--out", default=None, help="Output .opml path (default: input with .opml)")
    p.add_argument("--debug", action="store_true", help="Verbose logs")
    ns = p.parse_args(argv)
    if ns.debug:
        logger.setLevel(logging.DEBUG)
    return {
        "input": ns.input,
        "title": ns.title,
        "assume": ns.assume,
        "enable_ai": bool(ns.ai),
        "owner": ns.owner,
        "out": ns.out,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_argv(argv or sys.argv[1:])
    cfg = EngineConfig(enable_ai=args["enable_ai"], owner_name=args["owner"], title=args["title"])
    path = args["input"]
    if not os.path.exists(path):
        logger.error("Input not found: %s", path)
        return 2

    # Bypass detection if requested
    if args["assume"] == "html":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
        doc = build_opml_from_html(html, cfg)
    elif args["assume"] == "text":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read()
        doc = build_opml_from_text(txt, cfg)
    else:
        doc = build_opml_from_file(path, cfg)

    out_path = args["out"] or os.path.splitext(path)[0] + ".opml"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc.to_xml())
    logger.info("Wrote OPML: %s", out_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
