# RFCs and Examples — PiKit OPML Hypermap Project

This folder contains **draft RFCs** and **example hypermaps** for the PiKit project.

## Purpose
The goal is to extend OPML into a **protocol- and markup-agnostic hypermap format**.  
OPML hypermaps capture the *structure* of resources across the web and other protocols
(HTTP, Gemini, Gopher, IPFS, etc.) in a neutral, human-readable outline form.

### Key Principles
- **Structure, not content**: We map navigation hierarchies, links, and outlines — not article text.  
- **Respect boundaries**: Crawlers must honor `robots.txt` for HTTP(S) and analogous deny-lists.  
- **Transparency**: When links are omitted, placeholders SHOULD indicate deliberate omission.  
- **Extensibility**: Underscore-prefixed attributes carry optional metadata without breaking legacy OPML readers.

## Included Drafts
- **0001-opml-hypermap.md** — Defines OPML Hypermap profile.  
- **0002-opml-robots.md** — Defines voluntary omission lists.

## Example Hypermap
An OPML outline of the New York Times site navigation is included as a proof of concept.  
This demonstrates the **crawler + converter pipeline** and shows how PiKit represents complex site
structures as OPML trees.

⚠️ **Note:** The example does not reproduce article content. It is purely a structural outline.

## Acknowledgments
This work is inspired by Douglas C. Engelbart’s vision of hypertext as a tool for
collective knowledge building and augmentation.
