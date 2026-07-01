from __future__ import annotations

from webmcp_client import WebMCPClient


def main():
    client = WebMCPClient.from_env()

    status = client.status()
    print("status:", status.get("name") or status.get("title"), "actions:", status.get("action_count"))

    actions = client.list_actions()
    print("actions:", len(actions))
    assert actions, "Expected at least one action"

    names = {a.get("name") for a in actions}
    assert "open_kxci" in names, "Expected open_kxci action"
    assert "navigate_sitemap" in names, "Expected navigate_sitemap action"

    open_kxci = client.call_action("open_kxci", {})
    print("open_kxci ok:", open_kxci.get("ok"))
    assert open_kxci.get("ok") is True

    nav_valid = client.call_action("navigate_sitemap", {"value": "http://kxci.org"})
    print("navigate valid ok:", nav_valid.get("ok"))
    assert nav_valid.get("ok") is True

    nav_invalid = client.call_action("navigate_sitemap", {"value": "http://not-allowed.example"})
    print("navigate invalid ok:", nav_invalid.get("ok"))
    assert nav_invalid.get("ok") is False

    print("test_client.py: ok")


if __name__ == "__main__":
    main()
