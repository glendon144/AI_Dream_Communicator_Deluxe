# 🚀 PiKit v1.3.0 — Baseline OPML Hypermap Release

This release establishes a stable baseline for **PiKit** as an OPML Hypermap engine, inspired by Doug Engelbart’s vision of knowledge cartography.

---

### ✨ Highlights
- **Engine stability**
  - Removed duplicate OPML conversion builders.
  - Unified HTML and TEXT conversion functions.
  - Confirmed **batch + single OPML conversion** now working reliably.

- **Crawler**
  - Produces live OPML imports (e.g., New York Times site navigation and article feed).
  - Handles recursive OPML crawling.

- **RFC drafts**
  - **RFC 0001 — OPML Hypermap**: outlines OPML as a protocol- and markup-agnostic structural layer.
  - **RFC 0002 — OPML-Robots**: voluntary omission mechanism, respecting publisher boundaries.

- **Documentation**
  - `docs/rfcs/README.md` — context for RFCs.
  - Root `README.md` updated to set vision and philosophy.

- **Examples**
  - Sample OPML hypermaps from the New York Times navigation and article indexes.

---

### 📝 Notes
- PiKit maps **structure only** (sections, outlines, links), not article content.
- Malformed OPML warnings are shown rather than masked — helpful when converting raw AI output or non-OPML docs.
- This release anchors the project with both **working code** and a **design philosophy**.  

---

👉 Suggested next steps for v1.4:  
- Ordinal link navigation (green links for external articles).  
- Respecting robots.txt during crawling.  
- Interactive deep expansion of outlines.  
