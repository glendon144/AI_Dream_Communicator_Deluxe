# Release Notes — FunKit 1.20  (2025-08-24)

**Codename:** *Intraweb — Universal Reader*

## Highlights
- **Reader/Code view toggle** on `/doc/<id>` (`?mode=auto|reader|code`)  
  Auto mode renders as HTML if the body looks like HTML, otherwise shows a preformatted block.
- **FunKit branding** + green link color, plus polished layout.
- **Share link** box per document (copy to clipboard).
- **Index view modes:** `auto` (thumbnails only when available), `list` (compact), `gallery` (force thumbnails; optional `?ph=smile` placeholder).
- **Image handling:** supports Base64 inline or `exported_docs/assets/*.b64` through `/asset/<file>`.
- **Stability:** friendly 404/500 handlers; `/health` reports export dir + counts.
- **Launcher improvements:** Flask reads `PORT` from env; GUI helper can pick a free port and open a browser tab.
- **Exporter hardening:** non‑JSON types (e.g., `bytes`) are sanitized (Base64) to prevent crashes.

## Why this matters
Faithful OPML rendering laid the groundwork for HTML rendering. OPML’s outline structure maps naturally onto HTML’s DOM, so once FunKit rendered OPML correctly, **HTML “reader mode” came for free** — ad‑free, script‑free pages captured as durable documents.

## Upgrade
- Ensure Flask is installed:
  ```bash
  pip install flask
  ```
- Replace/merge `modules/flask_server.py` with the 1.20 version and keep your patched `modules/exporter.py`.
- Launch via GUI or run `python3 main.py`, then open `http://127.0.0.1:<port>/`.
- Visit `/health` for a quick check.

## Backward compatibility
- Existing exports remain valid. New image lifting/sanitization only **adds** fields and won’t break readers.

## Credits
- Design philosophy inspired by **Douglas Engelbart** (hyperlinks, outliners, multiple views).
