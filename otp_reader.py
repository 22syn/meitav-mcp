#!/usr/bin/env python3
"""
otp_reader.py — minimal, read-only iMessage OTP reader for macOS.
WHAT IT DOES (and nothing else):
  • Opens ~/Library/Messages/chat.db in READ-ONLY mode.
  • Looks only at INCOMING messages (is_from_me = 0) from the last N seconds.
  • Pulls the message body — including modern macOS (14+) where the text lives
    in the binary `attributedBody` blob instead of the `text` column.
  • Extracts a one-time / verification code using keyword-aware patterns.
  • Prints the freshest match. No sending, no writing, no network, no deps.
AUDIT NOTES (why this is safe to run):
  • The DB is opened with the SQLite `mode=ro` URI flag → this process literally
    cannot write to chat.db.
  • Standard library only. Grep this file for `import` — that's the whole list.
  • No socket / urllib / requests / subprocess anywhere. Nothing leaves the Mac.
  • It never touches any message you SENT, and by default only the last 5 minutes.
USAGE:
  python3 otp_reader.py                 # print the freshest OTP code (last 5 min)
  python3 otp_reader.py --json          # structured output for automation
  python3 otp_reader.py --window 120    # only look back 2 minutes
  python3 otp_reader.py --loose         # also accept a bare lone number (less safe)
  python3 otp_reader.py --debug         # show recent inbound previews (verify reading works)
REQUIREMENT: the app running this (Terminal / Claude) needs Full Disk Access:
  System Settings → Privacy & Security → Full Disk Access.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sqlite3
import sys
import time

APPLE_EPOCH = 978307200  # seconds between 1970-01-01 and 2001-01-01 (UTC)
DEFAULT_DB = os.path.expanduser("~/Library/Messages/chat.db")

# Keywords that signal a genuine code — English + Hebrew.
KEYWORD = (
    r"(?:code|otp|o\.t\.p|verification|verify|passcode|pass\s?code|pin|"
    r"one[\s-]?time|security\s+code|auth\w*|"
    r"קוד|אימות|סיסמ\w*|חד[\s-]?פעמי|אישור)"
)

# A 4–8 digit run NOT embedded in a longer number (keeps phone numbers out).
NUM = r"(?<!\d)(\d{4,8})(?!\d)"

# High-confidence patterns, tried in order.
PATTERNS = [
    ("apple_autofill", re.compile(r"#\s*" + NUM)),
    ("keyword_then_num", re.compile(KEYWORD + r"[^\d\n]{0,25}" + NUM, re.I)),
    ("num_then_keyword", re.compile(NUM + r"[^\d\n]{0,25}" + KEYWORD, re.I)),
]

BARE = re.compile(NUM)  # low-confidence fallback, only with --loose


def to_unix(raw: int) -> float:
    """message.date is ns-since-2001 (modern macOS) or s-since-2001 (legacy)."""
    if raw > 1e11:
        return raw / 1e9 + APPLE_EPOCH
    return raw + APPLE_EPOCH


def extract_body(text, blob) -> str:
    if text:
        return text
    if not blob:
        return ""
    return blob.decode("utf-8", "ignore")


_AB_NOISE = re.compile(
    r"streamtyped|NSMutableAttributedString|NSAttributedString|NSMutableString|"
    r"NSString|NSObject|NSDictionary|NSNumber|NSValue|__kIM\w*"
)


def clean_preview(body: str) -> str:
    s = _AB_NOISE.sub(" ", body)
    s = re.sub(r"[^\t\n\x20-\x7e -￿]", " ", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def find_code(body: str, loose: bool):
    for name, pat in PATTERNS:
        m = pat.search(body)
        if m:
            return m.group(1), "high", name
    if loose:
        nums = BARE.findall(body)
        if len(nums) == 1 and len(body) <= 160:
            return nums[0], "low", "bare_number"
    return None


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def fetch_inbound(db_path, limit):
    if not os.path.exists(db_path):
        sys.exit(f"chat.db not found at {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        has_ab = "attributedBody" in _columns(conn, "message")
        ab = ", m.attributedBody" if has_ab else ""
        rows = conn.execute(
            f"""
            SELECT m.ROWID, m.date, h.id AS sender, m.text{ab}
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.is_from_me = 0
            ORDER BY m.date DESC
            LIMIT ?;
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        out.append({
            "rowid": r[0],
            "ts": to_unix(r[1]),
            "sender": r[2],
            "body": extract_body(r[3], r[4] if has_ab else None),
        })
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Read the freshest iMessage OTP code.")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--window", type=int, default=300)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.add_argument("--loose", action="store_true")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args(argv)

    msgs = fetch_inbound(args.db, args.limit)
    now = time.time()

    if args.debug:
        for m in msgs:
            age = int(now - m["ts"])
            print(f"[{age:>5}s ago] {m['sender'] or '?':<22} {clean_preview(m['body'])[:70]!r}")
        return 0

    for m in msgs:
        if now - m["ts"] > args.window:
            break
        hit = find_code(m["body"], args.loose)
        if hit:
            code, confidence, rule = hit
            if args.json:
                print(json.dumps({
                    "code": code,
                    "confidence": confidence,
                    "rule": rule,
                    "sender": m["sender"],
                    "received": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m["ts"])),
                    "preview": clean_preview(m["body"])[:80],
                }, ensure_ascii=False))
            else:
                print(code)
            return 0

    if args.json:
        print(json.dumps(None))
    sys.stderr.write("No OTP found in the time window.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
