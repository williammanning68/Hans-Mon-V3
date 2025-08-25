import os
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import List, Tuple, Iterable, Dict

import yagmail

ROOT = Path(__file__).parent.resolve()
TRANSCRIPTS_DIR = ROOT / "transcripts"
HOBART_TZ = ZoneInfo("Australia/Hobart")


def load_keywords() -> List[Tuple[re.Pattern, str]]:
    """Load keywords from keywords.txt or KEYWORDS env var."""
    file_path = Path(os.environ.get("KEYWORDS_FILE", "keywords.txt"))
    raw_terms: List[str] = []
    if file_path.exists():
        for line in file_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                s = s[1:-1]
            raw_terms.append(s)

    if not raw_terms:
        env_val = os.environ.get("KEYWORDS", "")
        pieces = [p.strip() for p in re.split(r"[,\n]", env_val) if p.strip()]
        raw_terms.extend(pieces)

    patterns: List[Tuple[re.Pattern, str]] = []
    for term in raw_terms:
        pat = re.compile(re.escape(term), re.IGNORECASE)
        patterns.append((pat, term))
    return patterns


def pick_target_files() -> List[Path]:
    """Return transcript files to include."""
    TRANSCRIPTS_DIR.mkdir(exist_ok=True, parents=True)
    files = sorted(TRANSCRIPTS_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return []
    hours = int(os.environ.get("SCAN_WINDOW_HOURS", "0") or "0")
    if hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        selected = []
        for p in files:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                selected.append(p)
        return selected or [files[0]]
    else:
        return [files[0]]


def find_excerpts(text: str, patterns: List[Tuple[re.Pattern, str]],
                  context_chars: int = 220,
                  max_per_term: int = 6) -> Dict[str, List[str]]:
    """Find keyword excerpts with context."""
    excerpts: Dict[str, List[str]] = {label: [] for (_p, label) in patterns}
    for pat, label in patterns:
        for m in pat.finditer(text):
            if len(excerpts[label]) >= max_per_term:
                break
            start = max(0, m.start() - context_chars)
            end = min(len(text), m.end() + context_chars)
            chunk = text[start:end].replace("\r", "")
            chunk = re.sub(r"\s+", " ", chunk).strip()
            if not chunk.startswith(('.', '“', '"', '(', '[', '‘', "'")):
                chunk = "… " + chunk
            if not chunk.endswith(('.', '”', '"', ')', ']', '’', "'")):
                chunk = chunk + " …"
            excerpts[label].append(chunk)
    return {k: v for k, v in excerpts.items() if v}


def build_email_body(files: List[Path], patterns: List[Tuple[re.Pattern, str]],
                     context_chars: int, max_per_term: int) -> Tuple[str, int]:
    """Create the email body and return (body, total_hit_count)."""
    hobart_now = datetime.now(HOBART_TZ).strftime("%Y-%m-%d %H:%M %Z")
    lines: List[str] = []
    lines.append(f"Hansard keyword digest — generated {hobart_now}")
    if patterns:
        labels = ", ".join([lbl for (_p, lbl) in patterns])
        lines.append(f"Keywords: {labels}")
    lines.append("")

    total_hits = 0

    for fp in files:
        text = fp.read_text(encoding="utf-8", errors="ignore")
        excerpts = find_excerpts(text, patterns, context_chars=context_chars, max_per_term=max_per_term)
        file_hits = sum(len(v) for v in excerpts.values())

        nice_name = fp.name.replace("_", " ")
        lines.append(f"=== {nice_name} ===")
        if not excerpts:
            lines.append("No keyword hits found in this file.\n")
            continue

        for label, chunks in excerpts.items():
            lines.append(f"- {label} ({len(chunks)}):")
            for ex in chunks:
                lines.append(f"  • {ex}")
        lines.append("")
        total_hits += file_hits

    if total_hits == 0:
        lines.append("No keyword matches found. Attaching transcript(s) for reference.")

    return "\n".join(lines), total_hits


def main():
    EMAIL_USER = os.environ["EMAIL_USER"]
    EMAIL_PASS = os.environ["EMAIL_PASS"]
    EMAIL_TO = os.environ["EMAIL_TO"]

    patterns = load_keywords()
    if not patterns:
        raise SystemExit("No keywords found. Add keywords.txt or set KEYWORDS env var.")

    files = pick_target_files()
    if not files:
        raise SystemExit("No transcripts found in transcripts/")

    context_chars = int(os.environ.get("CONTEXT_CHARS", "220"))
    max_per_term = int(os.environ.get("MAX_EXCERPTS_PER_TERM", "6"))

    body, total_hits = build_email_body(files, patterns, context_chars, max_per_term)

    titles = ", ".join([f.stem[:50] for f in files])
    subject = f"Hansard digest ({total_hits} hits) — {titles}"

    to_list = [addr.strip() for addr in re.split(r"[,\s]+", EMAIL_TO) if addr.strip()]

    # ✅ Flexible SMTP: defaults to Gmail if no host/port set
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 587)

    yag = yagmail.SMTP(
        user=EMAIL_USER,
        password=EMAIL_PASS,
        host=host,
        port=port,
    )

    yag.send(
        to=to_list,
        subject=subject,
        contents=body,
        attachments=[str(p) for p in files],
    )
    print("✅ Email sent.")


if __name__ == "__main__":
    main()
