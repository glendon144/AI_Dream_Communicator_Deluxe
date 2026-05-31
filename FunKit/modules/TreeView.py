# modules/TreeView.py
# FunKit Document Tree viewer (standalone Tk widget)
# - Show IDs toggle
# - Show Numbers (Engelbart-style hierarchical numbers) toggle
# - Quick-jump by ID (accepts "1", "Doc 1", "Document 1", etc.)
# - Lazy-loading children (DB mode)
# - OPML/XML outline loading (HyperScope-inspired) in the same widget
# - Fallback: when no ancestry is available, Jump opens doc directly
#
# Integration sketch (in your GUI):
#   from modules.TreeView import open_tree_view
#   open_tree_view(root, repo=YourRepo(db_path),
#                  on_open_doc=self._on_link_click,
#                  root_doc_id=current_doc_id)

from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from dataclasses import dataclass
from typing import Optional, Callable, Iterable, List, Dict, Any
import re
import xml.etree.ElementTree as ET

# ----------------------------
# Data model contracts (DB mode)
# ----------------------------

@dataclass
class DocNode:
    id: int
    title: str
    parent_id: Optional[int]  # None if a root
    created_at: Optional[str] = None  # optional extras

class RepoProtocol:
    """
    Minimal repo interface TreeView needs. Plug your SQLite/doc layer here.
    """
    def get_doc(self, doc_id: int) -> Optional[DocNode]:
        raise NotImplementedError

    def get_children(self, parent_id: Optional[int]) -> Iterable[DocNode]:
        """
        Return children ordered as you like (e.g., created_at asc).
        If parent_id is None, return top-level roots.
        """
        raise NotImplementedError


# ----------------------------
# Outline model + OPML parsing (OPML mode)
# ----------------------------

@dataclass
class OutlineNode:
    text: str
    children: List["OutlineNode"]

    @staticmethod
    def from_etree(elem: ET.Element) -> "OutlineNode":
        text = (
            elem.attrib.get("text")
            or elem.attrib.get("title")
            or (elem.text.strip() if elem.text else "")
            or "[No Text]"
        )
        kids = [OutlineNode.from_etree(e) for e in list(elem) if e.tag.lower() in {"outline", "node", "item"}]
        return OutlineNode(text=text, children=kids)

def parse_opml(path: str) -> List[OutlineNode]:
    tree = ET.parse(path)
    root = tree.getroot()
    body = next((child for child in root if child.tag.lower().endswith("body")), None)
    if body is not None:
        return [OutlineNode.from_etree(e) for e in body.findall("outline")]
    # Fallback: treat any children as outline-y nodes
    return [OutlineNode.from_etree(e) for e in root]


# ----------------------------
# TreeView implementation (supports DB + OPML modes)
# ----------------------------

class TreeViewWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        repo: RepoProtocol,
        on_open_doc: Callable[[int], None],
        root_doc_id: Optional[int] = None,
        title: str = "FunKit Document Tree",
    ):
        super().__init__(master)
        self.title(title)
        self.geometry("720x560")
        self.minsize(520, 380)

        self.repo = repo
        self.on_open_doc = on_open_doc
        self.root_doc_id = root_doc_id

        # State
        self.mode: str = "db"  # or "opml"
        self.show_ids_var = tk.BooleanVar(value=True)
        self.show_nums_var = tk.BooleanVar(value=False)
        self._loaded_children: Dict[str, bool] = {}  # item_id -> loaded? (db mode)
        self._iid_to_id: Dict[str, int] = {}         # item_id -> doc_id (db mode)

        # UI
        self._build_toolbar()
        self._build_tree()
        self._build_statusbar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self.destroy())

        self._populate_initial()

    # ---------- UI Construction ----------

    def _build_toolbar(self):
        bar = ttk.Frame(self)
        bar.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        ttk.Label(bar, text="Quick-Jump ID:").pack(side=tk.LEFT)
        self.jump_entry = ttk.Entry(bar, width=16)
        self.jump_entry.pack(side=tk.LEFT, padx=(4, 8))
        self.jump_entry.bind("<Return>", self._on_jump)
        ttk.Button(bar, text="Jump", command=self._on_jump).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Checkbutton(bar, text="Show IDs", variable=self.show_ids_var, command=self._refresh_labels)\
            .pack(side=tk.LEFT)
        ttk.Checkbutton(bar, text="Show Numbers", variable=self.show_nums_var, command=self._toggle_numbers)\
            .pack(side=tk.LEFT, padx=(8, 0))

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Button(bar, text="Expand All", command=self._expand_all).pack(side=tk.LEFT)
        ttk.Button(bar, text="Collapse All", command=self._collapse_all).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Button(bar, text="Load OPML…", command=self._open_opml_dialog).pack(side=tk.LEFT)

    def _build_tree(self):
        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Tree with an extra column for hierarchical numbers
        self.tree = ttk.Treeview(container, columns=("num",), show="tree headings")
        self.tree.heading("num", text="No.")
        self.tree.column("num", width=0, minwidth=0, stretch=False, anchor="e")  # hidden by default

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        self.tree.bind("<<TreeviewOpen>>", self._on_open_node)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", self._on_open_selected)

        # Style tweak
        style = ttk.Style(self)
        try:
            style.configure("Treeview", rowheight=22)
        except tk.TclError:
            pass

    def _build_statusbar(self):
        self.status = tk.StringVar(value="Ready")
        bar = ttk.Frame(self)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(side=tk.LEFT, padx=8, pady=4)

    # ---------- Data Population ----------

    def _populate_initial(self):
        self.mode = "db"
        self.tree.delete(*self.tree.get_children(""))
        self._loaded_children.clear()
        self._iid_to_id.clear()

        if self.root_doc_id is not None:
            root_doc = self.repo.get_doc(self.root_doc_id)
            if not root_doc:
                self._set_status(f"Root doc {self.root_doc_id} not found. Showing all roots.")
                self._populate_roots()
                self._update_numbering()
                return
            root_iid = self._insert_doc("", root_doc)
            self._insert_placeholder(root_iid)  # lazy-load children
            self.tree.item(root_iid, open=True)
            self._set_status(f"Root: {self._label_for(root_doc)}")
        else:
            self._populate_roots()
        self._update_numbering()

    def _populate_roots(self):
        roots = list(self.repo.get_children(None))
        if not roots:
            self._set_status("No root documents found.")
            return
        for d in roots:
            iid = self._insert_doc("", d)
            self._insert_placeholder(iid)
        self._set_status(f"Loaded {len(roots)} roots.")

    # ---------- OPML Mode ----------

    def _open_opml_dialog(self):
        path = filedialog.askopenfilename(
            title="Open OPML/XML",
            filetypes=[("OPML / XML", "*.opml *.xml"), ("All files", "*.*")],
        )
        if path:
            self.load_opml_file(path)

    def load_opml_file(self, path: str):
        """Clear the tree and load nodes from an OPML/XML file."""
        try:
            nodes = parse_opml(path)
        except Exception as e:
            messagebox.showerror("OPML Load Failed", str(e))
            return

        self.mode = "opml"
        self.tree.delete(*self.tree.get_children(""))
        self._iid_to_id.clear()
        self._loaded_children.clear()

        def insert_nodes(parent_iid: str, outline_nodes: List[OutlineNode]):
            for node in outline_nodes:
                iid = self.tree.insert(parent_iid, "end", text=node.text)
                if node.children:
                    insert_nodes(iid, node.children)

        insert_nodes("", nodes)
        self._set_status(f"Loaded OPML: {path}")
        self._update_numbering()

    # ---------- Tree Helpers (DB mode insertions) ----------

    def _insert_doc(self, parent_iid: str, doc: DocNode) -> str:
        label = self._label_for(doc)
        iid = self.tree.insert(parent_iid, "end", text=label)
        self.tree.item(iid, open=False)
        try:
            self._iid_to_id[iid] = int(doc.id)
        except Exception:
            pass
        return iid

    def _insert_placeholder(self, iid: str):
        # Placeholder child signifies “expand to load”
        self.tree.insert(iid, "end", text="…")
        self._loaded_children[iid] = False

    def _load_children_if_needed(self, iid: str):
        if self.mode != "db":
            return  # OPML mode doesn't lazy-load
        if self._loaded_children.get(iid, True):
            return
        # Clear placeholder(s)
        for child in self.tree.get_children(iid):
            self.tree.delete(child)
        # Load actual children
        doc_id = self._doc_id_for_iid(iid)
        if doc_id is None:
            self._loaded_children[iid] = True
            self._update_numbering()
            return
        kids = list(self.repo.get_children(doc_id))
        for d in kids:
            kid_iid = self._insert_doc(iid, d)
            self._insert_placeholder(kid_iid)
        self._loaded_children[iid] = True
        self._update_numbering()

    def _label_for(self, doc: DocNode) -> str:
        title = (doc.title or "").strip() or "(untitled)"
        return f"{doc.id}: {title}" if self.show_ids_var.get() else title

    def _doc_id_for_iid(self, iid: str) -> Optional[int]:
        return self._iid_to_id.get(iid)

    def _refresh_labels(self):
        # Re-render row labels to show/hide IDs (DB mode only)
        def walk(parent=""):
            for iid in self.tree.get_children(parent):
                doc_id = self._doc_id_for_iid(iid)
                if doc_id is not None:
                    doc = self.repo.get_doc(doc_id)
                    if doc:
                        label = self._label_for(doc)
                        self.tree.item(iid, text=label)
                walk(iid)
        walk()
        self._update_numbering()
        self._set_status("Toggled Show IDs.")

    # ---------- Events ----------

    def _on_open_node(self, event=None):
        sel = self.tree.focus()
        if sel:
            self._load_children_if_needed(sel)

    def _on_double_click(self, event=None):
        self._on_open_selected()

    def _on_open_selected(self, event=None):
        sel = self.tree.focus()
        if not sel:
            return
        doc_id = self._doc_id_for_iid(sel)
        if doc_id is None:
            return  # OPML row or unknown
        try:
            self.on_open_doc(doc_id)
            self._set_status(f"Opened doc {doc_id}.")
        except Exception as e:
            messagebox.showerror("Open Document Error", str(e))

    def _on_jump(self, event=None):
        raw = self.jump_entry.get().strip()
        m = re.search(r"\d+", raw)
        if not m:
            self._set_status("Enter a numeric ID.")
            return
        target_id = int(m.group(0))
        self._jump_to_doc(target_id)

    # ---------- Jump / Find (DB mode) ----------

    def _jump_to_doc(self, doc_id: int):
        # Try visible first
        found = self._find_visible_iid(doc_id)
        if found:
            self._focus_and_reveal(found)
            return

        # Try to compute an ancestor chain (works if parent_id is available)
        path = self._compute_ancestor_chain(doc_id)
        if not path:
            # Fallback: open the doc directly via the host callback
            try:
                self.on_open_doc(doc_id)
                self._set_status(f"Opened doc {doc_id} (no ancestry available).")
            except Exception:
                self._set_status(f"Document {doc_id} not found.")
            return

        # Materialize and expand the path
        parent_iid = ""
        if self.root_doc_id is not None:
            top = self.tree.get_children("")
            if not top:
                self._set_status("Tree is empty.")
                return
            parent_iid = top[0]

        for ancestor_id in path:
            iid = self._ensure_child_item(parent_iid, ancestor_id)
            self.tree.item(iid, open=True)
            self._load_children_if_needed(iid)
            parent_iid = iid

        target_iid = self._ensure_child_item(parent_iid, doc_id)
        self._focus_and_reveal(target_iid)

    def _ensure_child_item(self, parent_iid: str, child_doc_id: int) -> str:
        # Try to find an existing child for this ID under parent_iid; else insert it.
        for iid in self.tree.get_children(parent_iid):
            if self._doc_id_for_iid(iid) == child_doc_id:
                return iid
        # Need to insert it (fetch doc)
        doc = self.repo.get_doc(child_doc_id)
        if not doc:
            # Create a stub for visibility
            doc = DocNode(id=child_doc_id, title="(missing)", parent_id=None)
        iid = self._insert_doc(parent_iid, doc)
        self._insert_placeholder(iid)
        return iid

    def _find_visible_iid(self, doc_id: int) -> Optional[str]:
        def walk(parent="") -> Optional[str]:
            for iid in self.tree.get_children(parent):
                if self._doc_id_for_iid(iid) == doc_id:
                    return iid
                found = walk(iid)
                if found:
                    return found
            return None
        return walk("")

    def _compute_ancestor_chain(self, doc_id: int) -> List[int]:
        """
        Returns ancestors from the first ancestor under the current root to the parent of doc_id.
        If the view is global (no root_doc_id), this returns the full chain from a root.
        Requires a real parent_id chain; if your repo doesn't provide it, this returns [].
        """
        chain: List[int] = []
        cur = self.repo.get_doc(doc_id)
        if not cur:
            return []
        # Walk explicit parent pointers; if your repo doesn't set them, this will no-op.
        while cur and cur.parent_id is not None:
            chain.append(cur.parent_id)
            cur = self.repo.get_doc(cur.parent_id)
        chain.reverse()
        # If we are in single-root mode, trim any ancestors above root_doc_id
        if self.root_doc_id is not None and chain and chain[0] != self.root_doc_id:
            if self.root_doc_id in chain:
                idx = chain.index(self.root_doc_id)
                chain = chain[idx:]  # include root
            else:
                return []
        return chain

    def _focus_and_reveal(self, iid: str):
        self.tree.see(iid)
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        # The #0 column holds text; use item text for status
        label = self.tree.item(iid, "text")
        self._set_status(f"Jumped to {label}")
        self._update_numbering()

    # ---------- Expand/Collapse ----------

    def _expand_all(self):
        def walk(parent=""):
            for iid in self.tree.get_children(parent):
                self._load_children_if_needed(iid)
                self.tree.item(iid, open=True)
                walk(iid)
        walk()
        self._update_numbering()
        self._set_status("Expanded all.")

    def _collapse_all(self):
        def walk(parent=""):
            for iid in self.tree.get_children(parent):
                self.tree.item(iid, open=False)
                walk(iid)
        walk()
        self._update_numbering()
        self._set_status("Collapsed all.")

    # ---------- Engelbart-style numbering ----------

    def _toggle_numbers(self):
        visible = bool(self.show_nums_var.get())
        # Show/hide the numbers column
        if visible:
            self.tree.column("num", width=90, minwidth=60, stretch=False, anchor="e")
        else:
            self.tree.column("num", width=0, minwidth=0, stretch=False)
            # Also clear values for cleanliness (optional)
            def clear(parent=""):
                for iid in self.tree.get_children(parent):
                    self.tree.set(iid, "num", "")
                    clear(iid)
            clear()
        self._update_numbering()

    def _update_numbering(self):
        if not self.show_nums_var.get():
            return

        # Compute hierarchical numbers like 1, 1.1, 1.2, 2, 2.1, ...
        def renumber(parent="", prefix: List[int] | None = None):
            prefix = prefix or []
            children = self.tree.get_children(parent)
            for idx, iid in enumerate(children, start=1):
                num_parts = prefix + [idx]
                num_str = ".".join(str(n) for n in num_parts)
                self.tree.set(iid, "num", num_str)
                # Recurse regardless of open/closed; numbering is structural
                renumber(iid, num_parts)
        renumber("")

    # ---------- Misc ----------

    def _set_status(self, msg: str):
        self.status.set(msg)

    def _on_close(self):
        self.destroy()


# ----------------------------
# Public API
# ----------------------------

def open_tree_view(
    master: tk.Misc,
    repo: RepoProtocol,
    on_open_doc: Callable[[int], None],
    root_doc_id: Optional[int] = None,
    title: str = "FunKit Document Tree",
) -> TreeViewWindow:
    """
    Open the TreeView window. Keep a reference if you want to call methods later.
    """
    win = TreeViewWindow(master, repo=repo, on_open_doc=on_open_doc, root_doc_id=root_doc_id, title=title)
    win.transient(master)
    win.grab_set()  # modal-ish; remove if you prefer modeless
    return win


# ----------------------------
# Optional: Tiny demo harness
#   Run `python -m modules.TreeView` to test with fake data.
# ----------------------------
if __name__ == "__main__":
    class MemoryRepo(RepoProtocol):
        def __init__(self, nodes: Dict[int, DocNode]):
            self.nodes = nodes
            self.children: Dict[Optional[int], List[DocNode]] = {}
            for n in nodes.values():
                self.children.setdefault(n.parent_id, []).append(n)
            for k in self.children:
                self.children[k].sort(key=lambda d: (d.parent_id is not None, d.id))

        def get_doc(self, doc_id: int) -> Optional[DocNode]:
            return self.nodes.get(doc_id)

        def get_children(self, parent_id: Optional[int]) -> Iterable[DocNode]:
            return list(self.children.get(parent_id, []))

    nodes = {
        1: DocNode(1, "Root A", None),
        2: DocNode(2, "Root B", None),
        3: DocNode(3, "A.1", 1),
        4: DocNode(4, "A.2", 1),
        5: DocNode(5, "A.1.a", 3),
        6: DocNode(6, "B.1", 2),
        7: DocNode(7, "B.1.a", 6),
    }

    def on_open(doc_id: int):
        print(f"OPEN {doc_id}")

    root = tk.Tk()
    root.withdraw()
    win = open_tree_view(root, repo=MemoryRepo(nodes), on_open_doc=on_open, root_doc_id=None)
    # Try OPML from demo: uncomment to test
    # win.load_opml_file("sample_outline.opml")
    root.mainloop()
