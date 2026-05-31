import readline  # noqa: F401


def run_text_loop(store, processor):
    print("Entering text-only mode. Commands: get <id>, ask <id> <prompt>, exit")
    while True:
        try:
            cmd = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        parts = cmd.strip().split(maxsplit=2)
        if not parts:
            continue
        action = parts[0].lower()
        if action in ("exit", "quit"):
            break
        if action == "get" and len(parts) >= 2:
            try:
                print(store.get_document_text(int(parts[1])))
            except Exception as e:
                print(f"Error: {e}")
        elif action == "ask" and len(parts) == 3:
            reply = processor.ask_question(parts[2])
            if reply:
                new_id = store.add_document("AI Response", reply)
                print(f"Response saved as document {new_id}")
        else:
            print("Usage: get <id>, ask <id> <prompt>, exit")
