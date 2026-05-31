# PiKit Hypermap (OPML)

PiKit extends **OPML** into a protocol- and markup-agnostic format for **hypermaps** —
navigable outlines that capture the *structure* of resources across the Web and beyond.

## Highlights
- **Protocol-agnostic**: Works with HTTP(S), Gemini, Gopher, IPFS, local files.
- **Markup-agnostic**: Converts HTML, Gemtext, Markdown, and AI-generated lists into outlines.
- **Respectful**: Honors `robots.txt` and voluntary exclusion lists (see `docs/rfcs/0002-opml-robots.md`).
- **Portable**: OPML is human-readable XML; unknown attributes are ignored by legacy tools.
- **Engelbart-inspired**: Designed as a tool for knowledge cartography and augmentation.

## What’s in this repo
- `docs/rfcs/0001-opml-hypermap.md` — OPML Hypermap draft
- `docs/rfcs/0002-opml-robots.md` — OPML-Robots draft
- `docs/rfcs/README.md` — Context & intent
- Example hypermaps (e.g., New York Times navigation)

⚠️ **Note:** PiKit maps *structure only* — links, sections, outlines.  
It does not scrape or republish article content.

## Quick vision
- Use OPML as a neutral **control plane**: outline nodes carry `_href`, `_proto`, `_media`, `_status`, etc.
- GUI lets you expand nodes on demand; Ctrl/Alt+Click can fetch children or open in a browser.
- Public exports respect publisher boundaries (robots + deny-lists).

## Acknowledgments
This work is inspired by **Douglas C. Engelbart** and the vision of hypertext
as an augmentation of human intellect and collaborative knowledge work.
