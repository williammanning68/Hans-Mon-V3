#!/usr/bin/env python3
"""
Email the latest downloaded Hansard transcript, plus a keyword digest.

Reads keywords from:
  1) keywords.txt  (one per line), or
  2) KEYWORDS env (comma-separated), else
  3) a small default list.

Env required (set as GitHub Actions secrets):
  EMAIL_USER, EMAIL_PASS, EMAIL_TO

Optional env:
  PARAGRAPH_RADIUS = "0"  # include neighboring paragraphs (0 or 1)
"""

import os
import glob
import re
from datetime import datetime

import yagmail

# -------- Settings / inputs --------

EMAIL_USER = os.environ["EMAIL_USER"]
EMAIL_PASS = os.environ["EMAIL_PASS"]
EMAIL_TO   = os.environ["EMAIL_TO"]

PARAGRAPH_RADIUS = int(os.environ.get("PARAGRAPH_RADIUS", "0"))  # 0 or 1 recommended


def load_keywords():
    """Load keywords from keywords.txt, or KEYWORDS env, or defaults."""
    if os.path.exists("keywords.txt"):
        with open("keywords.txt", "r", encoding="utf-8", errors="ignore") as f:
            kws = [ln.strip() for ln in f if ln.strip()]
            if kws:
                return kws
    env = os.environ.get("KEYWORDS", "")
    if env.strip():
        return [k.strip() for k in env.split(",") if k.strip()]
    return ["budget", "health", "education", "climate"]  # defaults


KEYWORDS = load_keywords()


# -------- Helpers --------

def find_latest_txt():
    """Find the newest .txt, preferring transcripts/ then repo root."""
    candidates = []
    candidates.extend(glob.glob("transcripts/*.txt"))
    candidates.extend(glob.glob("*.txt"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def split_paragraphs(text: str):
    """Split text into paragraphs by blank lines."""
    # Handles \n and \r\n, and any amount of whitespace between paragraphs
    return [p.strip() for p in re.split(r"\r?\n\s*\r?\n", text) if p.strip()]


def paragraph_digest(text: str, keywords, radius=0):
    """
    Return (digest_text, num_matches).
    Matches whole-word keywords (case-insensitive). Each match returns the
    paragraph; if radius=1, includes paragraph before/after as well.
    """
    paras = split_paragraphs(text)
    if not keywords:
        return "", 0

    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
                         re.IGNORECASE)

    snippets = []
    for i, p in enumerate(paras):
        if pattern.search(p):
            start = max(0, i - radius)
            end = min(len(paras), i + radius + 1)
            block = "\n\n".join(paras[start:end])
            snippets.append(block)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in snippets:
        if s not in seen:
            unique.append(s)
            seen.add(s)

    if not unique:
        return "No keywords matched in this transcript.", 0

    body = []
    for idx, u in enumerate(unique, 1):
        body.append(f"🔹 Match #{idx}\n{u}")
    return "\n\n".join(body), len(unique)


# -------- Main --------

def main():
    latest = find_latest_txt()
    if not latest:
        print("⚠️ No transcript .txt found (looked in transcripts/ and repo root).")
        return

    with open(latest, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    digest, count = paragraph_digest(content, KEYWORDS, PARAGRAPH_RADIUS)

    # Save digest alongside the transcript (handy as artifact)
    base = os.path.splitext(os.path.basename(latest))[0]
    digest_file = f"digest_{base}.txt"
    with open(digest_file, "w", encoding="utf-8") as df:
        df.write(digest)

    subject = f"Hansard Transcript & Digest: {os.path.basename(latest)}"
    human_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    header = (
        f"Time: {human_time}\n"
        f"Keywords: {', '.join(KEYWORDS)}\n"
        f"Matches found: {count}\n\n"
        f"=== EXCERPTS ===\n"
    )

    yag = yagmail.SMTP(EMAIL_USER, EMAIL_PASS)
    yag.send(
        to=EMAIL_TO,
        subject=subject,
        contents=header + digest + "\n\n(Full transcript attached.)",
        attachments=[latest]  # attach full transcript
    )

    print(f"✅ Email sent to {EMAIL_TO} with {latest} and digest ({count} matches).")


if __name__ == "__main__":
    main()
