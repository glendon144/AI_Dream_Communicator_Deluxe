from __future__ import annotations

import json

from relay_core import WebMCPRelay


def print_json(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    relay = WebMCPRelay()

    print(f"Fetched manifest from: {relay.snapshot.manifest_url}")
    print(f"Action count: {len(relay.actions)}")

    status = relay.call_tool("webmcp_manifest_status")
    print_json("webmcp_manifest_status", status)

    actions = relay.call_tool("webmcp_list_actions")
    print_json("webmcp_list_actions", actions)

    get_action = relay.call_tool("webmcp_get_action", {"action_name": "open_kxci"})
    print_json("webmcp_get_action open_kxci", get_action)

    open_kxci = relay.call_tool("webmcp_call_action", {"action_name": "open_kxci"})
    print_json("webmcp_call_action open_kxci", open_kxci)

    navigate_valid = relay.call_tool(
        "webmcp_call_action",
        {
            "action_name": "navigate_sitemap",
            "parameters": {"value": "http://kxci.org"},
        },
    )
    print_json("webmcp_call_action navigate_sitemap valid", navigate_valid)

    navigate_invalid = relay.call_tool(
        "webmcp_call_action",
        {
            "action_name": "navigate_sitemap",
            "parameters": {"value": "http://example.invalid"},
        },
    )
    print_json("webmcp_call_action navigate_sitemap invalid", navigate_invalid)

    assert status["ok"] is True
    assert actions["ok"] is True
    assert get_action["ok"] is True
    assert open_kxci["ok"] is True
    assert navigate_valid["ok"] is True
    assert navigate_invalid["ok"] is False
    assert "allowed_values" in navigate_invalid

    print("\nAll relay checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
