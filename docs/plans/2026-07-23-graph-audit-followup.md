> NEXT SESSION: review this plan before making structural changes to this repo, and report status to Kobi.

# Graph-Audit Follow-up — meitav-mcp (2026-07-23)

## Graph snapshot

- **Code symbols:** 25 (smallest repo in this audit; Python MCP server, venv on Python 3.12).
- **Top hubs (degree):**
  - `server.py` — 16 (MCP server entry; login + all portfolio tools)
  - `call_tool()` — 9 (in `server.py`; the tool dispatch handler)
  - `otp_reader.py` — 7 (reads SMS OTP from the Messages `chat.db`)
  - `_client()` — 7 (in `server.py`; HTTP/session client factory)
  - `fetch_inbound()` — 5 (in `otp_reader.py`)
- **Import cycles:** none.
- **Zero-edge nodes:** 0.
- **Age:** 17 days since last significant change.

## Change-risk hotspots

- **`server.py` (deg 16) + `call_tool()` (deg 9) + `_client()` (deg 7)** — the entire tool surface and the authenticated HTTP session both live here. `login`, `get_snapshot`, `get_performance`, `get_transactions` all route through `call_tool()`, and every data call depends on `_client()`. A change to the session/login flow can silently break all portfolio reads. Test the full `login → snapshot/performance/transactions` chain after any edit.
- **`otp_reader.py` (deg 7) + `fetch_inbound()` (deg 5)** — the OTP path that reads the local Messages database. Fragile against macOS Full-Disk-Access permissions and the SMS-vs-iMessage forwarding gotchas already documented in `CLAUDE.md`; treat as environment-coupled, not pure logic.

## Action items

**No structural action required — maintenance / watch-list only.**

- Clean graph: no cycles, no dead/orphaned nodes. Hub concentration in `server.py` is expected for a 25-symbol single-file MCP server.
- The real operational risk is environmental (venv interpreter path in `claude_desktop_config.json`, Full Disk Access, OTP forwarding) — already captured in the `CLAUDE.md` troubleshooting table, not something the graph can fix.
- Protect the login/session and OTP paths with manual verification when touched; no restructuring warranted today.
