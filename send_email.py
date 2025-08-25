#!/usr/bin/env python3
"""
send_email.py

Send a summary email for newly downloaded Hansard transcripts.  The script reads
``.last_run_manifest.json`` (written by ``download_transcript.py``) to discover
which files were saved in the latest run.  If no new files were saved the script
prints a message and exits without sending anything.

Environment variables (all optional unless noted):
  EMAIL_USER (required)  username/from address
  EMAIL_PASS (required)  password or app password
  EMAIL_TO   (required)  comma/space/semicolon separated recipient list
  SMTP_HOST               default "smtp.gmail.com"
  SMTP_PORT               default "465"

If a ``keywords.txt`` file (or ``KEYWORDS`` env var) is present, any matched
keywords are noted beside each filename in the email body.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yagmail

ROOT = Path(__file__).parent.resolve()
MANIFEST_PATH = ROOT / ".last_run_manifest.json"


def load_keywords() -> list[tuple[re.Pattern, str]]:
    """Load keywords from a file or KEYWORDS env var."""
    file_path = Path(os.environ.get("KEYWORDS_FILE", "keywords.txt"))
    raw_terms: list[str] = []
    if file_path.exists():
        for line in file_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if (line.startswith('"') and line.endswith('"')) or (
                line.startswith("'") and line.endswith("'")
            ):
                line = line[1:-1]
            raw_terms.append(line)

    if not raw_terms:
        env_val = os.environ.get("KEYWORDS", "")
        pieces = [p.strip() for p in re.split(r"[,\n]", env_val) if p.strip()]
        raw_terms.extend(pieces)

    patterns: list[tuple[re.Pattern, str]] = []
    for term in raw_terms:
        pat = re.compile(re.escape(term), re.IGNORECASE)
        patterns.append((pat, term))
    return patterns


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_recipients(raw: str) -> list[str]:
    return [p for p in re.split(r"[;,\s]+", raw) if p]


def main() -> None:
    manifest = load_manifest()
    new_count = manifest.get("new_count", 0)
    if new_count == 0:
        print("No new downloads this run; email not sent.")
        return

    EMAIL_USER = os.getenv("EMAIL_USER", "").strip()
    EMAIL_PASS = os.getenv("EMAIL_PASS", "").strip()
    EMAIL_TO = os.getenv("EMAIL_TO", "").strip()
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))

    if not (EMAIL_USER and EMAIL_PASS and EMAIL_TO):
        print("Missing email credentials; skipping email send.")
        return

    to_list = parse_recipients(EMAIL_TO)
    keywords = load_keywords()

    hobart = datetime.now(ZoneInfo("Australia/Hobart")).strftime("%Y-%m-%d %H:%M %Z")
    subject = f"Hansard updates – {new_count} new – {hobart}"

    lines = [f"{new_count} new transcript(s) downloaded at {hobart}.", ""]
    attachments: list[Path] = []
    for chamber, files in manifest.get("new_by_house", {}).items():
        lines.append(f"{chamber}:")
        for rel in files:
            p = ROOT / rel
            attachments.append(p)
            kw_hits: list[str] = []
            if keywords and p.exists():
                text = p.read_text(encoding="utf-8", errors="ignore")
                for pat, disp in keywords:
                    if pat.search(text):
                        kw_hits.append(disp)
            if kw_hits:
                lines.append(f"  • {Path(rel).name} (keywords: {', '.join(sorted(set(kw_hits)))} )")
            else:
                lines.append(f"  • {Path(rel).name}")
        lines.append("")

    body = "\n".join(lines).strip()

    try:
        yag = yagmail.SMTP(
            user=EMAIL_USER, password=EMAIL_PASS, host=SMTP_HOST, port=SMTP_PORT, smtp_ssl=True
        )
        yag.send(to=to_list, subject=subject, contents=body, attachments=attachments)
        print(f"Email sent to {', '.join(to_list)} with {len(attachments)} attachment(s).")
    except Exception as e:
        print(f"Failed to send email: {e}")


if __name__ == "__main__":
    main()

