# Changelog

## 1.20 — 2025-08-24
- Add document view toggle: `mode=auto|reader|code`.
- Preformatted `<pre>` for code/poetry/JSON with preserved indentation.
- Reader mode renders HTML safely (internal `[text](doc:ID)` links resolved).
- Green link theme; PiKit branding.
- Share link UI + clipboard copy.
- Index view modes (auto/list/gallery) with optional placeholder thumbnails.
- Base64 image support and `/asset/<file>` decoding; exporter sanitizes `bytes`.
- Friendly 404/500, `/health` endpoint.
- Flask `PORT` env + GUI free-port launch.
