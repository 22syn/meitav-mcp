# Meitav MCP

An [MCP](https://modelcontextprotocol.io) server that gives an AI agent (Claude, or any MCP-compatible client) direct, read-only access to your own **Meitav Dash** brokerage account: portfolio snapshot, monthly performance history, current holdings, and full transaction history — as structured JSON your agent can reason over, chart, or pipe into your own tools.

Everything runs **locally, on your own machine, with your own login**. There is no hosted service, no shared backend, and no third party (including the author) ever sees your credentials, session, or portfolio data.

## What it does

| Tool | Returns |
|---|---|
| `login(phone, id_number)` | Automates the Meitav Dash login (phone → SMS OTP → session cookies), saved to disk |
| `set_cookies(cookie_string)` | Manual fallback — paste cookies from an already-logged-in browser session |
| `get_snapshot()` | Current portfolio value, YTD %, all-time % |
| `get_performance()` | Full monthly return history |
| `get_holdings()` | Current equity positions (name, quantity, value, gain %) |
| `get_transactions(years)` | Full transaction history by year |

## Use cases

The tools above are building blocks — a few things you can do with them:

- A live dashboard of current holdings, driven straight from `get_holdings()`
- Return/performance charts over time from `get_performance()`
- Hook up additional agents on top of the same data for portfolio management or risk analysis

## How it works

- [`server.py`](server.py) is the MCP server. Data tools call Meitav Dash's own API directly over `httpx` using cookies saved locally at `~/.meitav/session.json` — nothing is proxied through any third-party server.
- `login()` drives a real, visible browser (Playwright) through the actual Meitav Dash login form, then waits for the SMS one-time code.
- [`otp_reader.py`](otp_reader.py) is a small, dependency-free, **read-only** script that reads that OTP straight out of your own Mac's local Messages database (`~/Library/Messages/chat.db`, opened with the SQLite `mode=ro` flag — it is physically unable to write to it) so you don't have to type the code in by hand. It only looks at inbound messages from the last few minutes and only extracts a short numeric code — see the file's own audit notes for exactly what it does and doesn't do.

## Platform support

The automated OTP auto-read (`otp_reader.py`) depends on macOS Messages / iMessage-SMS-forwarding, so it's **macOS-only** today. On Windows/Linux — or on a Mac without SMS forwarding set up — `login()` will time out waiting for the code; at that point just read the OTP off your phone and either:

- type it into the visible browser window yourself and let the flow continue, or
- log in fully in your own browser and hand the resulting cookies to `set_cookies(...)`.

Either path works cross-platform with zero extra setup. A native Windows OTP auto-read isn't currently implemented — see [Contributing](#contributing) if you want to add one.

## Requirements

- Python **3.10+** (the server uses `match/case`; macOS's system `python3` is often 3.9 — use a dedicated venv on a newer interpreter)
- [Claude Desktop](https://claude.ai/download) or any other MCP-compatible client

## Setup

```bash
git clone https://github.com/KobiHaz/meitav-mcp.git
cd meitav-mcp
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Add to your MCP client config (for Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "meitav": {
      "command": "/absolute/path/to/meitav-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/meitav-mcp/server.py"]
    }
  }
}
```

Restart your MCP client, then in a conversation:

```
login("050XXXXXXX")
get_snapshot()
get_performance()
get_holdings()
get_transactions()
```

On macOS, grant **Full Disk Access** to whichever app runs this server (e.g. Claude Desktop) under System Settings → Privacy & Security, so the OTP auto-read can open `chat.db`.

## Security & privacy

- Your Meitav Dash session cookies are written only to `~/.meitav/session.json` on your own disk — never committed, never transmitted anywhere except back to `customers.meitav.co.il`.
- `otp_reader.py` is standard-library only: no network calls, no writes, and it only ever reads your own inbound Messages.
- This repo ships with no credentials, API keys, or personal data of any kind. If you fork or extend it, keep it that way — check `.gitignore` covers anything you add.

## Disclaimer

This is an independent, unofficial project and is **not affiliated with, endorsed by, or connected to Meitav Dash** in any way. It automates the same login flow you'd otherwise do by hand in a browser. Use it at your own risk and make sure it complies with Meitav Dash's terms of service for your account.

## Contributing

Issues and PRs welcome — a native Windows/Linux OTP auto-read, other brokers, or additional data endpoints are all good places to start.

## License

MIT — see [LICENSE](LICENSE).
