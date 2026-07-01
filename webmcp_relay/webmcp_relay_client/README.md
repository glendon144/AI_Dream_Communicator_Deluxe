# WebMCP Relay Client

A small Flask cockpit for testing a local WebMCP relay server.

It is designed for the local relay project at:

`/home/gross/src/webmcp_relay`

The client can run in two modes:

1. `direct` mode: fetches the WebMCP manifest directly and returns safe instruction payloads.
2. `stdio` mode: calls the local MCP relay server over a simple stdio JSON-RPC subprocess.

Direct mode is the default because it is robust and lets you test the public manifest immediately. Stdio mode is useful for testing the relay server itself.

## Quick start

```bash
unzip webmcp_relay_client.zip
cd webmcp_relay_client
./run.sh
```

Then open:

```text
http://127.0.0.1:5054
```

## Configuration

Edit `.env`.

```bash
WEBMCP_CLIENT_MODE=direct
WEBMCP_MANIFEST_URL=http://jazz.clonesvr.com/.well-known/mcp.json
WEBMCP_RELAY_SERVER=/home/gross/src/webmcp_relay/server.py
FLASK_HOST=127.0.0.1
FLASK_PORT=5054
FLASK_DEBUG=1
```

To test the local MCP relay server:

```bash
WEBMCP_CLIENT_MODE=stdio
WEBMCP_RELAY_SERVER=/home/gross/src/webmcp_relay/server.py
./run.sh
```

If the relay server uses newline-delimited JSON-RPC on stdin/stdout, stdio mode should work. If the relay uses a different framing style, direct mode will still let you test the WebMCP action model.

## What it does

- Shows manifest status.
- Lists WebMCP actions.
- Lets you call actions safely.
- Validates `navigate_sitemap` enum values.
- Shows raw JSON response.
- Does not execute shell commands.
- Does not copy to clipboard.
- Does not perform hidden browser actions.

## API

```text
GET  /api/status
GET  /api/actions
GET  /api/action/<name>
POST /api/call
```
