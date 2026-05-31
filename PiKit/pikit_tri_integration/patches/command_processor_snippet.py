def cmd_TRIASK(self, args):
    """
    TRIASK <doc_id> [--instructions "..."]
    Run tri-model pipeline on the doc body, create a new doc with the result,
    and insert a green link in the source doc.
    """
    import shlex
    from modules.tri_pipeline import run_tri_pipeline
    from modules.ai_memory import get_memory, set_memory

    if not args:
        return "Usage: TRIASK <doc_id> [--instructions \"...\"]"

    parts = shlex.split(args)
    doc_id = int(parts[0])
    instructions = ""
    if "--instructions" in parts:
        i = parts.index("--instructions")
        if i + 1 < len(parts):
            instructions = parts[i+1]

    text = self.store.get_document_body(doc_id)
    conn = self.store.get_connection()
    memory = get_memory(conn, key="global")

    out = run_tri_pipeline(text, memory, instructions=instructions)
    new_id = self.store.create_document("Tri Synthesis", out.final)

    memory.setdefault("recent_immediate", [])
    memory["recent_immediate"] = (memory["recent_immediate"] + [out.immediate])[-10:]
    set_memory(conn, memory, key="global")

    # Insert your Green Link™
    self.hypertext.insert_green_link(doc_id, new_id)  # adapt to your helper
    return f"Created doc {new_id} via TRIASK"
