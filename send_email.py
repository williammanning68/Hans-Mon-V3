#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Send an email only when new Hansard transcripts were downloaded.

Inputs (preferred):
  --digest PATH              Path to the combined digest .txt produced by scan_new_transcripts.py
  --manifest PATH            Path to .last_run_manifest.json (default: ./ .last_run_manifest.json)

Environment:
  EMAIL_FROM                 (required) Gmail address used to send (e.g. you@gmail.com)
  EMAIL_TO                   (required) Comma/space/semicolon separated recipient list
  EMAIL_APP_PASSWORD         (required) Gmail App Password (no spaces)
  EMAIL_SMTP_HOST            (optional) default: smtp.gmail.com
  EMAIL_SMTP_PORT            (optional) default: 465
  EMAIL_SUBJECT_PREFIX       (optional) e.g. "[Hansard]"
  ATTACH_TRANSCRIPTS         (optional) "true"/"1" to attach all new transcripts (default: false)

If --digest is omitted, the script tries:
  1) DIGEST_PATH env var
  2) The newest file in ./digests/*.txt

If there were NO new downloads, the script prints a message and exits 0.
If credentials are missing/invalid, exits 1.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import yagmail  # pip install yagmail

ROOT = Path(__file__).parent.resolve()
DEFAULT_MANIFEST = ROOT / ".last_run_manifest.json"
DIGEST_DIR = ROOT / "digests"
KEYWORDS_FILE = ROOT / "keywords.txt"

def parse_args():
    ap = argparse.ArgumentParser(description="Email the latest Hansard digest if there were new downloads.")
    ap.add_argument("--digest", type=str, help="Path to the combined digest .txt")
    ap.add_argument("--manifest", type=str, default=str(DEFAULT_MANIFEST), help="Path to .last_run_manifest.json")
    return ap.parse_args()

def load_manifest(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def find_digest_from_dir():
    if not DIGEST_DIR.exists():
        return None
    txts = sorted(DIGEST_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(txts[0]) if txts else None

def load_keywords():
    if not KEYWORDS_FILE.exists():
        return []
    kws = []
    for line in KEYWORDS_FILE.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            kws.append(s)
    return kws

def recipients_list(s: str):
    # Split on comma/semicolon/space
    parts = []
    if not s:
        return parts
    for chunk in s.replace(";", ",").split(","):
        for sub in chunk.strip().split():
            if sub:
                parts.append(sub)
    return parts

def build_subject(prefix: str | None, total_new: int):
    hobart = datetime.now(ZoneInfo("Australia/Hobart")).strftime("%Y-%m-%d %H:%M %Z")
    core = f"Hansard digest – {total_new} new – {hobart}"
    return f"{prefix} {core}" if prefix else core

def build_body(manifest: dict, digest_path: str, keywords: list[str]):
    hobart = datetime.now(ZoneInfo("Australia/Hobart")).strftime("%Y-%m-%d %H:%M %Z")
    lines = []
    lines.append(f"New Hansard transcripts detected at {hobart}.")
    if keywords:
        lines.append(f"Keywords: {', '.join(keywords)}")
    lines.append("")

    # Show counts per House and list filenames
    new_by_house = (manifest or {}).get("new_by_house", {})
    total_new = (manifest or {}).get("new_count", 0)
    lines.append(f"Total new files: {total_new}")
    for house, files in new_by_house.items():
        lines.append(f"- {house}: {len(files)}")
        for p in files:
            lines.append(f"    • {Path(p).name}")
    lines.append("")
    lines.append("The attached digest includes the matched excerpts (if any) for today’s new files.")
    if digest_path:
        lines.append(f"Digest file: {Path(digest_path).name}")
    return "\n".join(lines)

def main():
    args = parse_args()

    # Resolve digest path
    digest_path = args.digest or os.getenv("DIGEST_PATH") or find_digest_from_dir()
    manifest_path = Path(args.manifest)

    manifest = load_manifest(manifest_path)
    total_new = (manifest or {}).get("new_count", 0)

    if total_new == 0:
        print("No new downloads this run; email not sent.")
        sys.exit(0)

    if not digest_path:
        print("ERROR: digest_path missing (no --digest, DIGEST_PATH, or file in ./digests).", file=sys.stderr)
        sys.exit(1)

    # Email configuration
    EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip()
    EMAIL_TO = os.getenv("EMAIL_TO", "").strip()
    EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "")  # strip spaces just in case
    SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "465"))
    SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "").strip()
    ATTACH_TRANSCRIPTS = os.getenv("ATTACH_TRANSCRIPTS", "").lower() in {"1", "true", "yes"}

    if not EMAIL_FROM or not EMAIL_TO or not EMAIL_APP_PASSWORD:
        print("ERROR: EMAIL_FROM, EMAIL_TO, and/or EMAIL_APP_PASSWORD not set.", file=sys.stderr)
        sys.exit(1)

    to_list = recipients_list(EMAIL_TO)
    if not to_list:
        print("ERROR: EMAIL_TO parsed to an empty recipient list.", file=sys.stderr)
        sys.exit(1)

    subject = build_subject(SUBJECT_PREFIX, total_new)
    keywords = load_keywords()
    body = build_body(manifest, digest_path, keywords)

    # Attachments: always digest. Optionally, all new transcripts.
    attachments = [digest_path]
    if ATTACH_TRANSCRIPTS:
        for files in (manifest or {}).get("new_by_house", {}).values():
            for fp in files:
                if fp and Path(fp).exists():
                    attachments.append(fp)

    # Send
    try:
        yag = yagmail.SMTP(user=EMAIL_FROM, password=EMAIL_APP_PASSWORD, host=SMTP_HOST, port=SMTP_PORT, smtp_ssl=True)
        yag.send(to=to_list, subject=subject, contents=body, attachments=attachments)
    except Exception as e:
        print(f"ERROR: failed to send email: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Email sent to {', '.join(to_list)} with subject: {subject}")
    print(f"Attached: {Path(digest_path).name}" + (" + transcripts" if ATTACH_TRANSCRIPTS else ""))

if __name__ == "__main__":
    main()
