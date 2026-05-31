# modules/flask_server.py
import os
import sys
import json
import re
import base64
import mimetypes
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

# ---- Paths ---------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "exported_docs"
ASSETS_DIR = DATA_DIR / "assets"  # optional: holds *.b64 files

# ---- Utilities -----------------------------------------------------------

def _s(val: Any, fallback: str = "") -> str:
    """Coerce any value to string safely."""
    if val is None:
        return fallback
    try:
        if isinstance(val, (str, int, float, bool)):
            return str(val)
        if isinstance(val, (dict, list, tuple, set)):
            return json.dumps(val, ensure_ascii=False)
        if isinstance(val, bytes):
            return f"<{len(val)} bytes>"
        return str(val)
    except Exception:
        return fallback

def _load_json(path: Path) -> Optional[Union[dict, list]]:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[flask_server] Skipping bad JSON: {path} ({e})", file=sys.stderr)
        return None

def _iter_docs() -> Iterable[Dict[str, Any]]:
    """Yield doc dicts from docs.json and per-file *.json."""
    if not DATA_DIR.exists():
        return []

    items: List[Dict[str, Any]] = []

    docs_file = DATA_DIR / "docs.json"
    if docs_file.exists():
        root = _load_json(docs_file)
        if isinstance(root, dict):
            items.append(root)
        elif isinstance(root, list):
            items.extend([d for d in root if isinstance(d, dict)])

    for file_path in sorted(DATA_DIR.glob("*.json")):
        if file_path.name == "docs.json":
            continue
        obj = _load_json(file_path)
        if obj is None:
            continue
        doc_id = file_path.stem
        if isinstance(obj, list):
            doc = next((d for d in obj if _s(d.get("id")) == doc_id), None)
        elif isinstance(obj, dict):
            doc = obj
            doc.setdefault("id", doc_id)
        else:
            doc = None
        if isinstance(doc, dict):
            items.append(doc)

    return items

def _find_doc(doc_id: str) -> Optional[Dict[str, Any]]:
    if not DATA_DIR.exists():
        return None

    fp = DATA_DIR / f"{doc_id}.json"
    if fp.exists():
        obj = _load_json(fp)
        if isinstance(obj, dict):
            obj.setdefault("id", doc_id)
            return obj
        if isinstance(obj, list):
            return next((d for d in obj if _s(d.get("id")) == doc_id), None)

    root = _load_json(DATA_DIR / "docs.json")
    if isinstance(root, dict):
        return root if _s(root.get("id")) == doc_id else None
    if isinstance(root, list):
        return next((d for d in root if _s(d.get("id")) == doc_id), None)
    return None

def _is_image_dict(d: Dict[str, Any]) -> bool:
    mime = _s(d.get("mime"))
    data_b64 = d.get("data_base64")
    file_ref = _s(d.get("file"))
    return mime.startswith("image/") and (isinstance(data_b64, str) or file_ref.endswith(".b64"))

def _collect_images(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    imgs: List[Dict[str, Any]] = []
    def add_img(d: Dict[str, Any]):
        if not isinstance(d, dict):
            return
        if _is_image_dict(d):
            imgs.append({
                "mime": _s(d.get("mime"), "image/png"),
                "data_base64": d.get("data_base64"),
                "file": _s(d.get("file")),
                "alt": _s(d.get("alt")),
                "caption": _s(d.get("caption")),
            })
    if isinstance(doc.get("images"), list):
        for it in doc["images"]:
            add_img(it)
    if isinstance(doc.get("attachments"), list):
        for it in doc["attachments"]:
            if isinstance(it, dict) and _s(it.get("kind")) == "image":
                add_img(it)
    return imgs

def _data_uri_or_asset(img: Dict[str, Any]) -> Optional[str]:
    mime = _s(img.get("mime"), "image/png")
    b64 = img.get("data_base64")
    file_ref = _s(img.get("file"))
    if isinstance(b64, str) and b64.strip():
        return f"data:{mime};base64,{b64}"
    if file_ref:
        return f"/asset/{file_ref}"
    return None

def _guess_mime_from_filename(name: str) -> str:
    if name.lower().endswith(".b64"):
        name = name[:-4]
    mt, _ = mimetypes.guess_type(name)
    return mt or "application/octet-stream"

# ---- Flask App -----------------------------------------------------------

def create_app():
    try:
        from flask import Flask, render_template_string, abort, Response
    except ImportError:
        print("Error: Flask is not installed. Run 'pip install flask'.", file=sys.stderr)
        sys.exit(1)

    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Error handlers
    @app.errorhandler(404)
    def _e404(_e):
        return (
            """<!doctype html><meta charset="utf-8">
            <title>Not found</title>
            <h3>Not found</h3><p>The requested item was not found.</p>
            <p><a href="/">← Back to index</a></p>""",
            404,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    @app.errorhandler(500)
    def _e500(e):
        print("[flask_server] 500:", e, file=sys.stderr)
        traceback.print_exc()
        return (
            """<!doctype html><meta charset="utf-8">
            <title>Server error</title>
            <h3>Internal Server Error</h3>
            <p>Something went wrong rendering this page.</p>
            <p><a href="/">← Back to index</a></p>""",
            500,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    @app.route("/health")
    def health():
        exists = DATA_DIR.exists()
        count = len(list(_iter_docs())) if exists else 0
        assets = ASSETS_DIR.exists()
        return {"status": "ok", "exported_docs_exists": exists, "doc_count": count, "assets_exists": assets}

    @app.route("/")
    def index():
        """Index page with optional thumbnails."""
        items = []
        note = ""
        if not DATA_DIR.exists():
            note = f"(Directory not found: {DATA_DIR})"

        for doc in _iter_docs():
            try:
                doc_id = _s(doc.get("id")) or _s(abs(hash(_s(doc.get("title")))) % (10**9))
                title = _s(doc.get("title", f"Document {doc_id}"))
                raw_desc = doc.get("description")
                if raw_desc is None:
                    raw_desc = doc.get("body", "")
                desc = _s(raw_desc).replace("\n", " ")[:80]

                # pick first image (if any) for thumbnail
                thumb_src = None
                imgs = _collect_images(doc)
                if imgs:
                    src = _data_uri_or_asset(imgs[0])
                    if src:
                        thumb_src = src

                items.append({"id": doc_id, "title": title, "desc": desc, "thumb": thumb_src})
            except Exception as e:
                print(f"[flask_server] Skipping bad doc on index: {e}", file=sys.stderr)

        template = """
        <!doctype html>
        <meta charset="utf-8" />
        <title>DemoKit Documents</title>
        <style>
          body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }
          ul.docs { list-style: none; padding: 0; margin: 0; }
          li.doc { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-bottom: 1px solid #eee; }
          img.thumb { display: block; width: 64px; height: 64px; object-fit: cover; border-radius: 6px; background: #f2f2f2; }
          .meta { line-height: 1.35; }
          .title { font-weight: 600; }
          .desc { color: #555; font-size: 0.92rem; }
          code { background: #f5f5f5; padding: 2px 4px; border-radius: 4px; }
          a { color: #0a58ca; text-decoration: none; }
          a:hover { text-decoration: underline; }
        </style>
        <h1>DemoKit Documents</h1>
        {% if note %}<p style="color:#a00;">{{ note }}</p>{% endif %}
        {% if items %}
          <ul class="docs">
          {% for item in items %}
            <li class="doc">
              {% if item.thumb %}
                <a href="/doc/{{ item.id }}"><img class="thumb" src="{{ item.thumb }}" alt=""></a>
              {% else %}
                <div style="width:64px;height:64px;border-radius:6px;background:#fafafa;border:1px solid #eee;"></div>
              {% endif %}
              <div class="meta">
                <div class="title"><a href="/doc/{{ item.id }}">{{ item.title }}</a></div>
                <div class="desc">{{ item.desc }}{% if item.desc %}…{% endif %}</div>
              </div>
            </li>
          {% endfor %}
          </ul>
        {% else %}
          <p>No documents found in <code>{{ data_dir }}</code>.</p>
        {% endif %}
        """
        return render_template_string(template, items=items, data_dir=str(DATA_DIR), note=note)

    @app.route("/doc/<doc_id>")
    def show_doc(doc_id):
        doc = _find_doc(_s(doc_id))
        if not doc:
            abort(404)

        title = _s(doc.get("title", f"Document {doc_id}"))
        body = _s(doc.get("body", ""))

        try:
            body_html = re.sub(r"\[(.+?)\]\(doc:(\d+)\)", r'<a href="/doc/\2">\1</a>', body)
        except Exception:
            body_html = _s(body)

        images = _collect_images(doc)
        image_html_snippets: List[str] = []
        for img in images:
            try:
                src = _data_uri_or_asset(img)
                if not src:
                    continue
                alt = _s(img.get("alt"))
                caption = _s(img.get("caption"))
                snippet = f'''
                  <figure class="img-figure">
                    <img src="{src}" alt="{alt}">
                    {f"<figcaption>{caption}</figcaption>" if caption else ""}
                  </figure>
                '''
                image_html_snippets.append(snippet)
            except Exception as e:
                print(f"[flask_server] Bad image skipped: {e}", file=sys.stderr)

        template = """
        <!doctype html>
        <meta charset="utf-8" />
        <title>{{ title }}</title>
        <style>
          body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }
          .content { max-width: 900px; }
          .img-figure { margin: 16px 0; }
          .img-figure img { max-width: 100%; height: auto; display: block; border-radius: 8px; }
          .img-figure figcaption { color: #555; font-size: 0.9rem; margin-top: 6px; }
          pre, code { background: #f7f7f7; padding: 6px 8px; border-radius: 6px; overflow-x: auto; }
          a { color: #0a58ca; text-decoration: none; }
          a:hover { text-decoration: underline; }
        </style>
        <div class="content">
          <h2>{{ title }}</h2>
          <div>{{ body_html|safe }}</div>
          {% if image_html_snippets %}
            <hr>
            <h3>Images</h3>
            {% for snip in image_html_snippets %}
              {{ snip|safe }}
            {% endfor %}
          {% endif %}
          <p><a href="/">← Back to index</a></p>
        </div>
        """
        return render_template_string(
            template,
            title=title,
            body_html=body_html,
            image_html_snippets=image_html_snippets,
        )

    @app.route("/asset/<path:filename>")
    def serve_asset(filename: str):
        from flask import abort
        if not ASSETS_DIR.exists():
            abort(404)
        file_path = (ASSETS_DIR / filename).resolve()
        try:
            file_path.relative_to(ASSETS_DIR)
        except Exception:
            abort(404)
        if not file_path.exists() or not file_path.is_file():
            abort(404)

        try:
            b64_data = file_path.read_text(encoding="utf-8")
            raw = base64.b64decode(b64_data, validate=True)
        except Exception as e:
            print(f"[flask_server] Failed to decode asset {file_path}: {e}", file=sys.stderr)
            abort(404)

        mime = _guess_mime_from_filename(file_path.name)
        return Response(raw, mimetype=mime)

    return app

# ---- Main ----------------------------------------------------------------

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG") == "1"
    port = int(os.environ.get("PORT", "5050"))
    app = create_app()
    app.run(host="127.0.0.1", port=port, debug=debug)

