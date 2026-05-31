#!/usr/bin/env python3
"""
gmail_janitor.py

A small Gmail automation tool for local, user-approved email management.

Default behavior is DRY RUN.
Nothing is changed unless you pass --do-it.

Examples:

  # Find messages from a sender, but change nothing
  python3 gmail_janitor.py --from cohenn@alignpromptfundssolutionsflagship.com --spam-trash

  # Actually mark those messages spam and move them to trash
  python3 gmail_janitor.py --from cohenn@alignpromptfundssolutionsflagship.com --spam-trash --do-it

  # Use an arbitrary Gmail search query
  python3 gmail_janitor.py --query 'from:(@alignpromptfundssolutionsflagship.com)' --spam-trash

  # Archive newsletters
  python3 gmail_janitor.py --from newsletter@example.com --archive --do-it

  # Apply a label
  python3 gmail_janitor.py --query 'from:someone@example.com older_than:90d' --label Old-Mail --do-it

  # Search Spam and Trash too
  python3 gmail_janitor.py --query 'from:(@example.com)' --include-spam-trash --spam-trash

  # Act on one specific Gmail API message id, as extracted by AI Navigator
  python3 gmail_janitor.py --message-id 19e60f2b02356971 --archive

Dependencies:

  python3 -m pip install --upgrade \
    google-api-python-client \
    google-auth-httplib2 \
    google-auth-oauthlib

OAuth files:

  Preferred:
    ~/.config/gmail-janitor/credentials.json
    ~/.config/gmail-janitor/token.json

  Fallback:
    ~/credentials.json
    ~/token.json
"""

import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

APP_DIR = os.path.expanduser("~/.config/gmail-janitor")
PREFERRED_CREDENTIALS = os.path.join(APP_DIR, "credentials.json")
PREFERRED_TOKEN = os.path.join(APP_DIR, "token.json")

FALLBACK_CREDENTIALS = os.path.expanduser("~/credentials.json")
FALLBACK_TOKEN = os.path.expanduser("~/token.json")


def choose_oauth_paths() -> Tuple[str, str]:
    """
    Prefer ~/.config/gmail-janitor, but fall back to ~/credentials.json and ~/token.json
    so this works immediately with Glen's current setup.
    """
    if os.path.exists(PREFERRED_CREDENTIALS):
        return PREFERRED_CREDENTIALS, PREFERRED_TOKEN

    return FALLBACK_CREDENTIALS, FALLBACK_TOKEN


def get_gmail_service():
    credentials_path, token_path = choose_oauth_paths()

    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"Missing OAuth credentials file: {credentials_path}\n"
            "Expected either:\n"
            f"  {PREFERRED_CREDENTIALS}\n"
            "or:\n"
            f"  {FALLBACK_CREDENTIALS}"
        )

    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path,
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(token_path), exist_ok=True)

        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())

        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass

    return build("gmail", "v1", credentials=creds)


def build_query(args) -> str:
    if args.query:
        return args.query

    if args.sender:
        return f"from:{args.sender}"

    raise ValueError("You must provide either --from or --query.")


def list_matching_messages(
    service,
    query: str,
    max_messages: int,
    include_spam_trash: bool,
) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    page_token: Optional[str] = None

    while len(messages) < max_messages:
        batch_size = min(500, max_messages - len(messages))

        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=batch_size,
                pageToken=page_token,
                includeSpamTrash=include_spam_trash,
            )
            .execute()
        )

        messages.extend(response.get("messages", []))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return messages


def list_thread_message_ids(service, thread_id: str) -> List[Dict[str, str]]:
    """Return message ids belonging to a Gmail API thread id."""
    thread = (
        service.users()
        .threads()
        .get(userId="me", id=thread_id, format="metadata")
        .execute()
    )
    return [{"id": msg["id"]} for msg in thread.get("messages", []) if msg.get("id")]


def get_or_create_label_id(service, label_name: str, do_it: bool) -> Optional[str]:
    labels_response = service.users().labels().list(userId="me").execute()
    labels = labels_response.get("labels", [])

    for label in labels:
        if label.get("name") == label_name:
            return label.get("id")

    if not do_it:
        return None

    created = (
        service.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )

    return created.get("id")


def fetch_message_summary(service, message_id: str) -> Dict[str, str]:
    """
    Fetch lightweight metadata so dry-runs are useful.
    """
    msg = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"],
        )
        .execute()
    )

    headers = msg.get("payload", {}).get("headers", [])
    header_map = {h.get("name", ""): h.get("value", "") for h in headers}

    return {
        "id": message_id,
        "from": header_map.get("From", ""),
        "subject": header_map.get("Subject", ""),
        "date": header_map.get("Date", ""),
        "snippet": msg.get("snippet", ""),
    }


def print_message_summary(summary: Dict[str, str], prefix: str = ""):
    print(f"{prefix}Message ID: {summary.get('id', '')}")
    print(f"{prefix}From:       {summary.get('from', '')}")
    print(f"{prefix}Date:       {summary.get('date', '')}")
    print(f"{prefix}Subject:    {summary.get('subject', '')}")

    snippet = summary.get("snippet", "")
    if snippet:
        print(f"{prefix}Snippet:    {snippet[:160]}")

    print()


def compute_label_changes(args, label_id: Optional[str]) -> Tuple[List[str], List[str]]:
    add_labels: List[str] = []
    remove_labels: List[str] = []

    if args.spam or args.spam_trash:
        add_labels.append("SPAM")
        remove_labels.append("INBOX")

    if args.archive:
        remove_labels.append("INBOX")

    if args.mark_read:
        remove_labels.append("UNREAD")

    if args.mark_unread:
        add_labels.append("UNREAD")

    if args.star:
        add_labels.append("STARRED")

    if args.unstar:
        remove_labels.append("STARRED")

    if label_id:
        add_labels.append(label_id)

    return add_labels, remove_labels


def apply_label_changes(service, message_id: str, add_labels: List[str], remove_labels: List[str]):
    if not add_labels and not remove_labels:
        return

    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={
            "addLabelIds": add_labels,
            "removeLabelIds": remove_labels,
        },
    ).execute()


def process_message(
    service,
    message_id: str,
    args,
    label_id: Optional[str],
):
    summary = fetch_message_summary(service, message_id)

    if not args.do_it:
        print_message_summary(summary, prefix="[DRY RUN] ")

        planned = []

        if args.spam:
            planned.append("mark as spam")

        if args.spam_trash:
            planned.append("mark as spam and move to trash")

        if args.trash:
            planned.append("move to trash")

        if args.archive:
            planned.append("archive")

        if args.mark_read:
            planned.append("mark read")

        if args.mark_unread:
            planned.append("mark unread")

        if args.star:
            planned.append("star")

        if args.unstar:
            planned.append("unstar")

        if args.label:
            planned.append(f'apply label "{args.label}"')

        if planned:
            print("[DRY RUN] Planned action:", ", ".join(planned))
        else:
            print("[DRY RUN] No action selected.")

        print("-" * 72)
        return

    add_labels, remove_labels = compute_label_changes(args, label_id)
    apply_label_changes(service, message_id, add_labels, remove_labels)

    if args.trash or args.spam_trash:
        service.users().messages().trash(
            userId="me",
            id=message_id,
        ).execute()

    print_message_summary(summary, prefix="[DONE] ")
    print("-" * 72)


def validate_args(args):
    selectors = [bool(args.sender), bool(args.query), bool(args.message_id), bool(args.thread_id)]
    if not any(selectors):
        raise ValueError("You must provide --from, --query, --message-id, or --thread-id.")

    if sum(1 for item in selectors if item) > 1:
        raise ValueError("Choose only one selector: --from, --query, --message-id, or --thread-id.")

    actions = [
        args.spam,
        args.spam_trash,
        args.trash,
        args.archive,
        args.mark_read,
        args.mark_unread,
        args.star,
        args.unstar,
        bool(args.label),
    ]

    if not any(actions):
        raise ValueError(
            "No action selected. Choose one of: "
            "--spam, --spam-trash, --trash, --archive, --mark-read, "
            "--mark-unread, --star, --unstar, or --label."
        )

    if args.mark_read and args.mark_unread:
        raise ValueError("Choose either --mark-read or --mark-unread, not both.")

    if args.star and args.unstar:
        raise ValueError("Choose either --star or --unstar, not both.")

    if args.spam_trash and args.archive:
        raise ValueError("Choose either --spam-trash or --archive, not both.")

    if args.trash and args.archive:
        raise ValueError("Choose either --trash or --archive, not both.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Safely automate Gmail cleanup using Gmail API OAuth."
    )

    selector = parser.add_argument_group("message selection")
    selector.add_argument(
        "--from",
        dest="sender",
        help="Select messages from this sender address.",
    )
    selector.add_argument(
        "--query",
        help="Use an arbitrary Gmail search query.",
    )
    selector.add_argument(
        "--message-id",
        dest="message_id",
        help="Act on a specific Gmail API message id. Useful when AI Navigator extracts the current Gmail message from the browser pane.",
    )
    selector.add_argument(
        "--thread-id",
        dest="thread_id",
        help="Act on every message in a specific Gmail API thread id.",
    )
    selector.add_argument(
        "--include-spam-trash",
        action="store_true",
        help="Include messages already in Spam or Trash.",
    )
    selector.add_argument(
        "--max",
        type=int,
        default=50,
        help="Maximum number of messages to process. Default: 50.",
    )

    actions = parser.add_argument_group("actions")
    actions.add_argument(
        "--spam",
        action="store_true",
        help="Mark matching messages as Spam.",
    )
    actions.add_argument(
        "--spam-trash",
        action="store_true",
        help="Mark matching messages as Spam and move them to Trash.",
    )
    actions.add_argument(
        "--trash",
        action="store_true",
        help="Move matching messages to Trash.",
    )
    actions.add_argument(
        "--archive",
        action="store_true",
        help="Archive matching messages by removing them from Inbox.",
    )
    actions.add_argument(
        "--label",
        help="Apply this Gmail label. Created if missing when --do-it is used.",
    )
    actions.add_argument(
        "--mark-read",
        action="store_true",
        help="Mark matching messages as read.",
    )
    actions.add_argument(
        "--mark-unread",
        action="store_true",
        help="Mark matching messages as unread.",
    )
    actions.add_argument(
        "--star",
        action="store_true",
        help="Star matching messages.",
    )
    actions.add_argument(
        "--unstar",
        action="store_true",
        help="Remove star from matching messages.",
    )

    safety = parser.add_argument_group("safety")
    safety.add_argument(
        "--do-it",
        action="store_true",
        help="Actually modify Gmail. Without this, the script only performs a dry run.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    try:
        validate_args(args)

        mode = "LIVE" if args.do_it else "DRY RUN"

        print(f"Mode: {mode}")
        if args.message_id:
            print(f"Message ID: {args.message_id}")
        elif args.thread_id:
            print(f"Thread ID: {args.thread_id}")
        else:
            query = build_query(args)
            print(f"Query: {query}")
        print(f"Max messages: {args.max}")
        print(f"Include Spam/Trash: {args.include_spam_trash}")
        print()

        service = get_gmail_service()

        label_id = None
        if args.label:
            label_id = get_or_create_label_id(service, args.label, args.do_it)
            if not label_id and not args.do_it:
                print(f'[DRY RUN] Label "{args.label}" does not exist yet.')
                print(f'[DRY RUN] It would be created if you rerun with --do-it.')
                print()

        if args.message_id:
            messages = [{"id": args.message_id}]
        elif args.thread_id:
            messages = list_thread_message_ids(service, args.thread_id)
        else:
            query = build_query(args)
            messages = list_matching_messages(
                service=service,
                query=query,
                max_messages=args.max,
                include_spam_trash=args.include_spam_trash,
            )

        if not messages:
            print("No matching messages found.")
            return

        print(f"Found {len(messages)} matching message(s).")
        print("-" * 72)

        for message in messages:
            process_message(
                service=service,
                message_id=message["id"],
                args=args,
                label_id=label_id,
            )

        if not args.do_it:
            print()
            print("Dry run complete. Nothing was changed.")
            print("Rerun with --do-it to apply the planned action.")

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
