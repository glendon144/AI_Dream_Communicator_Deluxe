#!/usr/bin/env python3
"""
Command-line interface for DemoKit using the SQLite-backed DocumentStore and
 the currently selected AI provider.
"""

import argparse
import sys

from modules.app_runtime import build_processor


def main():
    parser = argparse.ArgumentParser(
        prog="demokit-cli",
        description="Manage documents and interact with AI via the command line",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    imp = subparsers.add_parser("import", help="Import documents from a CSV file into the database")
    imp.add_argument("csvfile", help="Path to input CSV (title,body rows)")

    exp = subparsers.add_parser("export", help="Export all documents from the database to a CSV file")
    exp.add_argument("csvfile", help="Path to output CSV")

    subparsers.add_parser("list", help="List document IDs and summaries")

    view = subparsers.add_parser("view", help="View a document by ID")
    view.add_argument("id", type=int, help="Document ID to view")

    ask = subparsers.add_parser("ask", help="Ask the AI to expand on a prompt or existing document")
    ask.add_argument("doc_id", nargs="?", type=int, help="Optional source document ID to link from")
    ask.add_argument("prompt", nargs="+", help="Prompt text for the AI")

    args = parser.parse_args()

    store, _ai, processor = build_processor()

    if args.command == "import":
        try:
            store.import_csv(args.csvfile)
            print(f"Imported CSV into database from '{args.csvfile}'")
        except Exception as e:
            print(f"Error importing CSV: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "export":
        try:
            store.export_csv(args.csvfile)
            print(f"Exported database documents to CSV '{args.csvfile}'")
        except Exception as e:
            print(f"Error exporting CSV: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list":
        for doc_id, summary in store.list_documents():
            print(f"{doc_id}: {summary}")

    elif args.command == "view":
        doc = store.get_document(args.id)
        if not doc:
            print(f"No document found with ID {args.id}", file=sys.stderr)
            sys.exit(2)
        created_at = doc["created_at"] if hasattr(doc, "keys") and "created_at" in doc.keys() else "unknown"
        print(f"Document {doc['id']} - {doc['title']} (created {created_at})\n")
        print(store.get_document_text(args.id))

    elif args.command == "ask":
        prompt_text = " ".join(args.prompt)
        if args.doc_id:
            processor.query_ai(
                prompt_text,
                args.doc_id,
                lambda new_id: print(f"AI response saved as document {new_id}"),
                lambda *_: None,
            )
        else:
            reply = processor.ask_question(prompt_text)
            if reply:
                new_id = store.add_document("AI Response", reply)
                print(f"AI response saved as document {new_id}")
            else:
                print("No reply from AI.")


if __name__ == "__main__":
    main()
