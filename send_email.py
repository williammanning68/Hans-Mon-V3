#!/usr/bin/env python3
"""
Email digests for all newly downloaded transcripts in this run.

Inputs:
  - new_files.txt (one path per line), created by scan_and_download.py
  - keywords from keywords.txt OR KEYWORDS env (comma-separated)

Secrets (GitHub Actions):
  EMAIL_USER, EMAIL_PASS, EMAIL_TO

Optional:
  PARAGRAPH_RADIUS = "0" or "1"
"""

import os
import re
from datetime import datetime, UTC
from pathlib import Path
import yagmail

ROOT = Path(__file__).parent.resolve()

EMAIL_USER = os.environ["EMAIL_USER"]
EMAIL_PASS = os.environ["EMAIL_PASS"]
EMAIL_TO   = os.environ["EMAIL_TO"]
PARAGRAPH_RADIUS = int(os.environ.get("PARAGRAPH_RADIUS", "0"))

def load_keywords():
    # ENV takes priority so you can drive tests from the workflow
    env = os.environ.get("KEYWORDS", "")
    if env.strip():
        return [k.strip() for k in env.split(",") if k.strip()]
    fpath = ROOT / "keywords.txt"
    if fpath.exists():
        kws = [ln.strip() for ln in fpath.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        if kws:
            return kws
    return ["budget", "health", "education", "climate"]

KEYWORDS = load_keywords()
pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in KEYWORDS) + r")\b", re.IGNORECASE)

def split_paragraphs(txt: str):
    return [p.strip() for p in re.split(r"\r?\n\s*\r?\n", txt) if p.strip()]

def digest_for(text: str, radius: int):
    paras = split_paragraphs(text)
    hits = []
    for i, p in enumerate(paras):
        if pattern.search(p):
            start = max(0, i - radius)
            end = min(len(paras), i + radius + 1)
            hits.append("\n\n".join(paras[start:end]))
    # dedupe preserving order
    seen, uniq = set(), []
    for h in hits:
        if h not in seen:
            uniq.append(h)
            seen.add(h)
    return uniq

def main():
    list_file = ROOT / "new_files.txt"
    if not list_file.exists():
        print("No new_files.txt — nothing new this run.")
        return

    files = [ln.strip() for ln in list_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not files:
        print("new_files.txt empty.")
        return

    sections = []
    attachments = []
    total_matches = 0

    for path in files:
        p = Path(path)
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        snippets = digest_for(txt, PARAGRAPH_RADIUS)
        total_matches += len(snippets)
        header = f"===== {p.name} =====\nMatches: {len(snippets)}\n"
        body = "\n\n".join(f"• Match {i+1}\n{sn}" for i, sn in enumerate(snippets)) if snippets else "No keywords matched."
        sections.append(header + body + "\n")
        attachments.append(str(p))

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"Hansard: {len(files)} new transcript(s) — {total_matches} match(es)"
    preface = (
        f"Time: {timestamp}\n"
        f"Keywords: {', '.join(KEYWORDS)}\n"
        f"PARAGRAPH_RADIUS: {PARAGRAPH_RADIUS}\n\n"
        "=== EXCERPTS ===\n\n"
    )

    yag = yagmail.SMTP(EMAIL_USER, EMAIL_PASS)
    yag.send(
        to=EMAIL_TO,
        subject=subject,
        contents=preface + "\n".join(sections) + "\n(Full transcripts attached.)",
        attachments=attachments
    )
    print(f"✅ Email sent to {EMAIL_TO} for {len(files)} file(s), {total_matches} match(es).")

if __name__ == "__main__":
    main()
