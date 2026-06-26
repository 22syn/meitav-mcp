# Meitav MCP — Setup Instructions for Claude Code

## What this is
MCP server that gives Claude direct access to Meitav Dash portfolio data.
Automated login: phone → SMS OTP (read from iMessage) → session cookies saved.

## Your job: install, configure, test

### Step 1 — Install Python dependencies
> ⚠️ Requires **Python 3.10+** (the server uses `match/case`, and the `mcp`
> package needs 3.10+). The macOS system `python3` is 3.9.6 — too old. Use a
> dedicated venv built from `python3.12`.
```bash
/opt/homebrew/bin/python3.12 -m venv /Users/kobihazout/meitav-mcp/.venv
/Users/kobihazout/meitav-mcp/.venv/bin/python -m pip install mcp httpx playwright
/Users/kobihazout/meitav-mcp/.venv/bin/python -m playwright install chromium
```

### Step 2 — Add to Claude Desktop config
File: `~/Library/Application Support/Claude/claude_desktop_config.json`

If the file doesn't exist yet, create it. If it exists, merge the `mcpServers` block.
Point `command` at the **venv** interpreter — not bare `python3`.

Add this entry under `mcpServers`:
```json
"meitav": {
  "command": "/Users/kobihazout/meitav-mcp/.venv/bin/python",
  "args": ["/Users/kobihazout/meitav-mcp/server.py"]
}
```

Full file example if starting fresh:
```json
{
  "mcpServers": {
    "meitav": {
      "command": "/Users/kobihazout/meitav-mcp/.venv/bin/python",
      "args": ["/Users/kobihazout/meitav-mcp/server.py"]
    }
  }
}
```

### Step 3 — Test the server starts
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' | /Users/kobihazout/meitav-mcp/.venv/bin/python ~/meitav-mcp/server.py
```
Expected: a JSON response with `"result"` and `"serverInfo": {"name": "meitav-mcp"}`.
If you see that → server is working.

### Step 4 — Restart Claude Desktop
Quit and reopen Claude Desktop. The `meitav` MCP should appear in the tools list.

## Done — how to use

After restart, in any Claude conversation:
1. `login("050XXXXXXX")` — logs in (browser opens, OTP auto-read from iMessage)
2. `get_snapshot()` — current portfolio value + returns
3. `get_performance()` — full monthly history
4. `get_transactions()` — all transactions

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No module named 'mcp'` | Install into the venv: `.venv/bin/python -m pip install mcp` |
| `No module named 'playwright'` | `.venv/bin/python -m pip install playwright && .venv/bin/python -m playwright install chromium` |
| `SyntaxError: match name:` | Wrong Python — the config must point at `.venv/bin/python` (3.12), not system `python3` (3.9.6). |
| OTP not found / `unable to open database file` | Grant **Full Disk Access to Claude Desktop** (the app that runs this MCP) in System Settings → Privacy & Security → Full Disk Access. Then restart Claude Desktop. |
| OTP arrives on the iPhone but `read_otp` says "No OTP found" | The code came as a **green SMS** that isn't syncing to the Mac. On the iPhone: **Settings → Messages → Text Message Forwarding → enable this Mac**. SMS codes then appear in the Mac's Messages (`chat.db`) and are auto-read. Until then, type the code into the login browser manually. |
| `meitav` entry disappears from config after restart | Claude Desktop rewrites `claude_desktop_config.json` with its in-memory list on quit, erasing edits made while it was running. Fix: **fully quit Claude Desktop first**, then add the `meitav` block to the file, then relaunch (it reads the file fresh at launch). |
| Login fills the wrong fields / prefix not selected | The Meitav form has a **prefix dropdown (`prefixPhone`, 050–058) + 7-digit `phoneNumber` field + 9-digit `identity` (ת"ז) field** — not one combined phone field. `tool_login` handles this; pass both `phone` and `id_number`. |
| Server doesn't appear in Claude | Check JSON syntax in claude_desktop_config.json, restart Claude Desktop |
| Session expired | Call `login()` again |
