#!/usr/bin/env python3
"""
Meitav Dash MCP Server
======================
Exposes Meitav Dash portfolio data as MCP tools.

Auth flow:
  1. Call `login(phone)` → Playwright opens Meitav, enters phone, waits for SMS OTP,
     reads it via otp_reader.py, enters it, extracts cookies → saved to disk.
  2. All data tools use saved cookies via direct httpx calls (fast, no browser needed).

Data API base: https://customers.meitav.co.il/v4/api/Trade/

Tools:
  login              Full automated login: phone → OTP → cookies saved
  read_otp           Read the latest Meitav OTP from iMessage (standalone)
  set_cookies        Manually paste cookies (fallback if login fails)
  get_snapshot       Portfolio value, YTD%, all-time%
  get_performance    Monthly return history
  get_transactions   Full transaction history by year
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    TextContent,
    Tool,
)

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "https://customers.meitav.co.il/v4/api/Trade"
LOGIN_URL = "https://customers.meitav.co.il/v2/login/loginAmit"
SESSION_FILE = Path.home() / ".meitav" / "session.json"
SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

OTP_READER = Path(__file__).parent / "otp_reader.py"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Referer": "https://customers.meitav.co.il/v2/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
}

# ── Session helpers ───────────────────────────────────────────────────────────

def load_session() -> dict[str, str]:
    if SESSION_FILE.exists():
        return json.loads(SESSION_FILE.read_text())
    return {}


def save_session(cookies: dict[str, str]) -> None:
    SESSION_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))


def _client(cookies: dict[str, str]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=HEADERS,
        cookies=cookies,
        follow_redirects=False,
        timeout=30.0,
    )


async def _check_auth(cookies: dict[str, str]) -> bool:
    async with _client(cookies) as c:
        r = await c.get(f"{BASE_URL}/GetTsuotDetail")
        return r.status_code == 200


# ── OTP reader ────────────────────────────────────────────────────────────────

def _read_otp_raw(window_seconds: int = 300) -> dict | None:
    result = subprocess.run(
        [sys.executable, str(OTP_READER), "--json", "--window", str(window_seconds), "--loose"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        return json.loads(result.stdout.strip())
    return None


async def _wait_for_otp(window: int = 120, poll_interval: int = 4, max_wait: int = 90) -> str | None:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        hit = _read_otp_raw(window_seconds=window)
        if hit:
            return hit["code"]
        await asyncio.sleep(poll_interval)
    return None


# ── Login via Playwright ──────────────────────────────────────────────────────

async def tool_login(phone: str, id_number: str = "") -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return (
            "❌ Playwright not installed. Run:\n"
            "  pip3 install playwright && python3 -m playwright install chromium"
        )

    if not phone.strip():
        return "❌ Phone number required."

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        await page.goto(LOGIN_URL, wait_until="networkidle")
        await asyncio.sleep(2)

        # Real Meitav login form (verified live):
        #   <select ng-model="prefixPhone">  options 050…058  → phone prefix
        #   <input name="identity" maxlength=9>   → תעודת זהות
        #   <input name="phoneNumber" maxlength=7> → the 7 digits AFTER the prefix
        #   submit button text: אישור
        digits = "".join(ch for ch in phone if ch.isdigit())
        prefix, rest = digits[:3], digits[3:]

        # Prefix dropdown.
        for sel in ('select[ng-model="prefixPhone"]', 'select[name="prefixPhone"]'):
            try:
                await page.select_option(sel, prefix, timeout=3000)
                break
            except Exception:
                continue

        # Israeli ID (תעודת זהות).
        if id_number.strip():
            for sel in ('input[name="identity"]', '#id-identity-input',
                        'input[ng-model="identity"]', 'input[placeholder*="זהות"]'):
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        await el.fill(id_number.strip())
                        break
                except Exception:
                    continue

        # Phone number — 7 digits only (prefix lives in the dropdown above).
        phone_input = None
        for sel in ('input[name="phoneNumber"]', 'input[ng-model="phoneNumber"]',
                    'input[placeholder*="טלפון"]'):
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    phone_input = el
                    break
            except Exception:
                continue

        if phone_input is None:
            await browser.close()
            return "❌ Could not find phone input. Page structure may have changed."

        await phone_input.fill(rest)

        submit_selectors = [
            'button:has-text("אישור")',
            'button:has-text("שלחו לי")',
            'button[type="submit"]',
            'button:has-text("שלח")',
            'button:has-text("כניסה")',
            'button:has-text("המשך")',
            'input[type="submit"]',
        ]
        submitted = False
        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            await page.keyboard.press("Enter")

        await asyncio.sleep(3)

        otp = await _wait_for_otp(window=120, poll_interval=4, max_wait=90)
        if not otp:
            await browser.close()
            return (
                "❌ OTP not received within 90s. "
                "Check Full Disk Access is granted to Terminal."
            )

        otp_selectors = [
            'input[type="number"]',
            'input[name="otp"]',
            'input[name="code"]',
            'input[placeholder*="קוד"]',
            'input[ng-model*="otp"]',
            'input[ng-model*="code"]',
            'input[ng-model*="Code"]',
            'input[maxlength="6"]',
            'input[maxlength="5"]',
            'input[maxlength="4"]',
        ]
        otp_input = None
        for sel in otp_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    otp_input = el
                    break
            except Exception:
                continue

        if otp_input is None:
            await browser.close()
            return f"❌ OTP received ({otp}) but OTP input field not found on page."

        await otp_input.fill(otp)

        # Some Meitav flows ask for the ID alongside the OTP — fill if present.
        if id_number.strip():
            for sel in ('input[ng-model="identity"]', 'input[placeholder*="זהות"]', 'input#id-identity-input'):
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=1000):
                        await el.fill(id_number.strip())
                        break
                except Exception:
                    continue

        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    break
            except Exception:
                continue
        else:
            await page.keyboard.press("Enter")

        try:
            await page.wait_for_url("**/home/**", timeout=15000)
        except Exception:
            pass

        # The trade API (BASE_URL) authenticates with the trade-area session cookie
        # (SessionTrade), which is only issued after the trade section loads. Visit it
        # before capturing cookies, otherwise the saved session 401s on trade calls.
        try:
            await page.goto("https://customers.meitav.co.il/tradeTnuot",
                            wait_until="networkidle")
            await asyncio.sleep(3)
        except Exception:
            pass

        raw_cookies = await ctx.cookies()
        cookies = {c["name"]: c["value"] for c in raw_cookies
                   if "meitav.co.il" in c.get("domain", "")}
        await browser.close()

        if not cookies:
            return "❌ No Meitav cookies found after login. Try set_cookies manually."

        ok = await _check_auth(cookies)
        if not ok:
            return f"⚠️ Cookies extracted ({len(cookies)}) but API check failed. Try again or use set_cookies."

        save_session(cookies)
        return (
            f"✅ Login successful. {len(cookies)} cookies saved.\n"
            f"OTP used: {otp}\n"
            "Ready: get_snapshot, get_performance, get_transactions."
        )


# ── Tool handlers ─────────────────────────────────────────────────────────────

async def tool_read_otp(window: int = 300) -> str:
    hit = _read_otp_raw(window_seconds=window)
    if not hit:
        return f"No OTP found in the last {window} seconds."
    return json.dumps(hit, ensure_ascii=False, indent=2)


async def tool_set_cookies(cookie_string: str) -> str:
    if cookie_string.strip().startswith("{"):
        cookies = json.loads(cookie_string)
    else:
        cookies = {}
        for part in cookie_string.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()

    if not cookies:
        return "❌ No cookies parsed."

    ok = await _check_auth(cookies)
    if not ok:
        return "❌ Session invalid. Make sure you are logged in to Meitav Dash in Chrome."

    save_session(cookies)
    return f"✅ Session saved ({len(cookies)} cookies). Ready to fetch data."


async def tool_get_snapshot() -> str:
    cookies = load_session()
    if not cookies:
        return "❌ No session. Run login first."

    async with _client(cookies) as c:
        r = await c.get(f"{BASE_URL}/GetTsuotDetail")

    if r.status_code in (401, 403):
        return "❌ Session expired. Run login again."
    if r.status_code != 200:
        return f"❌ API error {r.status_code}"

    d = r.json()
    return json.dumps({
        "portfolio_value_nis": d.get("TikAmount"),
        "as_of_date": (d.get("TrDate") or "")[:10],
        "return_all_time_pct": d.get("TshoaFirst"),
        "return_ytd_pct": d.get("TshoaFirstYear"),
    }, ensure_ascii=False, indent=2)


async def tool_get_performance() -> str:
    cookies = load_session()
    if not cookies:
        return "❌ No session. Run login first."

    async with _client(cookies) as c:
        r = await c.get(f"{BASE_URL}/GetTsuot")

    if r.status_code in (401, 403):
        return "❌ Session expired. Run login again."
    if r.status_code != 200:
        return f"❌ API error {r.status_code}"

    result = []
    for row in r.json():
        result.append({
            "year": row.get("Year"),
            "month": row.get("Month"),
            "monthly_return_pct": row.get("TsuaMonthly"),
            "account_value_nis": round(row.get("ShoviMonthly", 0)),
            "deposits_nis": row.get("Hafkadot", 0),
            "withdrawals_nis": row.get("Meshichot", 0),
            "ytd_return_pct": row.get("TsuaStartYear"),
            "return_since_start_pct": row.get("TsuaStartActivity"),
        })

    return json.dumps({"total_months": len(result), "months": result},
                      ensure_ascii=False, indent=2)


async def tool_get_holdings() -> str:
    """Current portfolio positions (authoritative). Uses GetYitrot — the actual
    holdings balance — NOT derived from transaction history. Equity rows only;
    cash/FX/tax rows are excluded."""
    cookies = load_session()
    if not cookies:
        return "❌ No session. Run login first."

    async with _client(cookies) as c:
        r = await c.get(f"{BASE_URL}/GetYitrot")

    if r.status_code in (401, 403):
        return "❌ Session expired. Run login again."
    if r.status_code != 200:
        return f"❌ API error {r.status_code}"

    EQUITY = {"מניות זרות", "מניות בש\"ח"}
    holdings = []
    for row in r.json():
        typ = (row.get("teurSugNiar") or "").strip()
        if typ not in EQUITY:
            continue  # skip cash / FX / tax (פח"ק, מט"ח מזומן)
        qty = row.get("kamut") or 0
        if qty <= 0:
            continue
        holdings.append({
            "security_name": (row.get("shemNiar") or "").strip(),
            "security_id": str(row.get("misparNiar")),
            "quantity": qty,
            "security_type": typ,
            "value_nis": round(row.get("shovi", 0)),
            "gain_pct": row.get("achuzRevach"),
        })

    return json.dumps({"count": len(holdings), "holdings": holdings},
                      ensure_ascii=False, indent=2)


async def tool_get_transactions(years: list[int] | None = None) -> str:
    cookies = load_session()
    if not cookies:
        return "❌ No session. Run login first."

    if not years:
        import datetime
        years = list(range(2021, datetime.date.today().year + 1))

    all_tx = []
    async with _client(cookies) as c:
        for year in years:
            r = await c.get(f"{BASE_URL}/GetTnuot", params={"selectedYear": year})
            if r.status_code in (401, 403):
                return "❌ Session expired. Run login again."
            if r.status_code != 200:
                return f"❌ API error {r.status_code} for year {year}"
            data = r.json()
            if data:
                all_tx.extend(data)

    normalized = [{
        "date": (t.get("tarichPeula") or "")[:10],
        "type": t.get("teurPeula"),
        "security_name": t.get("shemNiar"),
        "security_id": t.get("misparNiar"),
        "quantity": t.get("kamut"),
        "price": t.get("shaar"),
        "fee": t.get("amala"),
        "value_nis": t.get("shovi"),
        "cash_balance_nis": t.get("yitratShovi"),
        "qty_balance": t.get("yitratKamut"),
        "account": t.get("misparHeshbon"),
    } for t in all_tx]

    return json.dumps({
        "years_fetched": years,
        "total_transactions": len(normalized),
        "transactions": normalized,
    }, ensure_ascii=False, indent=2)


# ── MCP server ────────────────────────────────────────────────────────────────

server = Server("meitav-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="login",
            description=(
                "Fully automated Meitav Dash login. "
                "Opens a browser, enters your phone number, waits for the SMS OTP "
                "(reads it automatically from iMessage), enters it, and saves "
                "session cookies to disk. Run once; cookies persist until session expires."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Meitav phone number (e.g. 0501234567)"},
                    "id_number": {"type": "string", "description": "Israeli ID / תעודת זהות (e.g. 205874233)"}
                },
                "required": ["phone"]
            }
        ),
        Tool(
            name="read_otp",
            description="Read the latest Meitav OTP code from iMessage.",
            inputSchema={
                "type": "object",
                "properties": {
                    "window_seconds": {"type": "integer", "description": "Look-back window (default 300s)"}
                }
            }
        ),
        Tool(
            name="set_cookies",
            description=(
                "Manually provide session cookies (fallback if login fails). "
                "Paste the Cookie header from Chrome DevTools → Network → any Meitav request."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "cookie_string": {"type": "string", "description": "Raw Cookie header or JSON dict"}
                },
                "required": ["cookie_string"]
            }
        ),
        Tool(
            name="get_snapshot",
            description="Current portfolio value (NIS), YTD return (%), all-time return (%).",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_performance",
            description="Full monthly return history since account opened.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_holdings",
            description="Current portfolio positions (authoritative, from GetYitrot — "
                        "actual holdings, not derived from transactions). Equity only.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_transactions",
            description="Full transaction history. Optionally filter by years (e.g. [2024, 2025]).",
            inputSchema={
                "type": "object",
                "properties": {
                    "years": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Years to fetch. Omit for all (2021–now)."
                    }
                }
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None = None) -> list[TextContent]:
    args = arguments or {}

    try:
        match name:
            case "login":
                result = await tool_login(args.get("phone", ""), args.get("id_number", ""))
            case "read_otp":
                result = await tool_read_otp(args.get("window_seconds", 300))
            case "set_cookies":
                result = await tool_set_cookies(args["cookie_string"])
            case "get_snapshot":
                result = await tool_get_snapshot()
            case "get_performance":
                result = await tool_get_performance()
            case "get_holdings":
                result = await tool_get_holdings()
            case "get_transactions":
                result = await tool_get_transactions(args.get("years"))
            case _:
                result = f"❌ Unknown tool: {name}"
    except Exception as e:
        result = f"❌ {type(e).__name__}: {e}"

    return [TextContent(type="text", text=result)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
