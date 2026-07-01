# webmcp_relay

`webmcp_relay` is a conservative local bridge from a published WebMCP manifest to locally callable MCP tools.

It exists so local agents can discover and call tools derived from a WebMCP manifest without having to understand the raw WebMCP JSON format themselves. In this first version, the relay converts WebMCP actions into safe, structured MCP tool responses instead of silently driving a browser or executing commands.

## What It Does

- Fetches a WebMCP manifest from `WEBMCP_MANIFEST_URL` or the default `http://jazz.clonesvr.com/.well-known/mcp.json`
- Parses manifest metadata including `mcp_version`, `name`, `title`, `description`, `homepage`, `safety`, and `actions`
- Exposes built-in MCP tools for manifest inspection and validated action calls
- Exposes one MCP tool per WebMCP action in the manifest
- Returns structured instructions by default rather than performing clipboard, shell, install, or hidden browser actions

## Why It Exists

WebMCP is a public discovery format for websites. MCP is the local tool protocol many desktop agents and brokers understand. This relay is the brokered bridge:

`WebMCP manifest -> local MCP relay -> safe MCP tools for local agents`

That design keeps policy enforcement local and prepares the relay for future AI Broker workflows.

## Safety Model

Policy is enforced in [policy.py](/home/gross/src/webmcp_relay/policy.py):

- Clipboard actions require user initiation
- Installer, model, and git clone commands are never executed
- Navigation actions are user-visible only
- Unknown methods are denied
- No shell execution
- No automatic download or install
- No hidden browser activity

`WEBMCP_ALLOW_BROWSER_CONTROL=0` is the default. In that mode, all tool calls return instructions only.

If `WEBMCP_ALLOW_BROWSER_CONTROL=1`, the relay may open the manifest homepage for safe click-based navigation actions using Python's `webbrowser` module. It still does not perform clipboard execution, shell execution, or automated installer/model actions.

## Limitations

This project does not use the official Python MCP SDK because it was not available locally in this environment and no framework dependencies were preinstalled. Instead, it implements a small stdio JSON-RPC MCP server surface that supports:

- `initialize`
- `tools/list`
- `tools/call`

That is enough for basic local MCP client integration and testing, but it is not a full SDK-backed implementation yet.

## Files

- [server.py](/home/gross/src/webmcp_relay/server.py): stdio MCP server
- [relay_core.py](/home/gross/src/webmcp_relay/relay_core.py): manifest-backed relay logic
- [manifest.py](/home/gross/src/webmcp_relay/manifest.py): manifest fetcher
- [policy.py](/home/gross/src/webmcp_relay/policy.py): safety policy layer
- [logging_setup.py](/home/gross/src/webmcp_relay/logging_setup.py): local logging setup
- [test_relay.py](/home/gross/src/webmcp_relay/test_relay.py): command-line test script

Logs are written to `logs/webmcp_relay.log`.

## How To Run

Start the local MCP relay over stdio:

```bash
python3 server.py
```

Override the manifest URL:

```bash
WEBMCP_MANIFEST_URL=http://jazz.clonesvr.com/.well-known/mcp.json python3 server.py
```

Enable optional browser opening for safe navigation actions:

```bash
WEBMCP_ALLOW_BROWSER_CONTROL=1 python3 server.py
```

## Connect A Local MCP Client

Because the server runs over stdio, a local MCP client that supports stdio servers can point at:

```json
{
  "mcpServers": {
    "webmcp_relay": {
      "command": "python3",
      "args": ["/home/gross/src/webmcp_relay/server.py"]
    }
  }
}
```

This implementation exposes both built-in relay tools and dynamic per-action tools derived from the manifest.

## Built-In Tools

- `webmcp_manifest_status`
- `webmcp_list_actions`
- `webmcp_get_action`
- `webmcp_call_action`

## Example Tool Calls And Responses

Calling `open_kxci` returns a structured instruction payload like:

```json
{
  "ok": true,
  "action": "open_kxci",
  "description": "Open the KXCI radio button.",
  "method": "click",
  "selector": "[data-mcp='btn-kxci']",
  "homepage": "http://jazz.clonesvr.com",
  "safety": "navigation must be user-visible",
  "suggested_browser_instruction": "Open homepage, find selector, perform user-visible click.",
  "browser_opened": false
}
```

Calling `navigate_sitemap` with a valid enum value returns:

```json
{
  "ok": true,
  "action": "navigate_sitemap",
  "method": "setValueAndChange",
  "selector": "select.combobox[name='SiteMap']",
  "value": "http://kxci.org",
  "safety": "navigation must be user-visible"
}
```

Invalid enum values are denied and include the allowed values.

## Verification

```bash
python3 -m py_compile *.py
python3 test_relay.py
```
