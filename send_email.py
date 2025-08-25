import os
import re
import glob
import yagmail
from pathlib import Path
from datetime import datetime

# --- Helpers ---

def load_keywords():
    """Load keywords from keywords.txt or KEYWORDS env var"""
    if os.path.exists("keywords.txt"):
        with open("keywords.txt", encoding="utf-8") as f:
            return [kw.strip() for kw in f if kw.strip()]
    if "KEYWORDS" in os.environ:
        return [kw.strip() for kw in os.environ["KEYWORDS"].split(",") if kw.strip()]
    return []


def split_paragraphs(text):
    """Split transcript into paragraphs."""
    return re.split(r"\n\s*\n", text)


def detect_speaker(paragraph):
    """Detect speaker name at start of paragraph."""
    first_line = paragraph.strip().split("\n", 1)[0]
    if re.match(r"^(Mr|Ms|Mrs|Hon|Premier)\b", first_line):
        return first_line.strip()
    return None


def extract_matches(text, keywords):
    """Find keyword matches and return structured results."""
    results = []
    paragraphs = split_paragraphs(text)

    for para in paragraphs:
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", para, re.IGNORECASE):
                # Extract 2–3 sentences around keyword
                sentences = re.split(r"(?<=[.!?])\s+", para.strip())
                for i, s in enumerate(sentences):
                    if kw.lower() in s.lower():
                        start = max(0, i - 1)
                        end = min(len(sentences), i + 2)
                        snippet = " ".join(sentences[start:end])
                        speaker = detect_speaker(para)
                        results.append((kw, snippet.strip(), speaker))
                        break
    return results


def parse_date_from_filename(filename):
    """Extract datetime from Hansard filename, e.g. House_of_Assembly_Tuesday_3_June_2025.txt"""
    m = re.search(r"(\d{1,2} \w+ \d{4})", filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%d %B %Y")
        except ValueError:
            return datetime.min
    return datetime.min


def build_digest(files, keywords):
    """Build the digest body text for email."""
    all_matches = []
    body_lines = []

    # Header
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    body_lines.append(f"Time: {now}")
    body_lines.append("Keywords: " + ", ".join(keywords))

    # Process each transcript file
    total_matches = 0
    for f in sorted(files, key=lambda x: parse_date_from_filename(Path(x).name)):
        text = Path(f).read_text(encoding="utf-8", errors="ignore")
        matches = extract_matches(text, keywords)
        if not matches:
            continue
        total_matches += len(matches)

        body_lines.append(f"\n=== {Path(f).name} ===")
        for i, (kw, snippet, speaker) in enumerate(matches, 1):
            if speaker:
                body_lines.append(f"🔹 Match #{i} ({speaker})")
            else:
                body_lines.append(f"🔹 Match #{i}")
            body_lines.append(snippet)
            body_lines.append("")

    body_lines.insert(2, f"Matches found: {total_matches}\n")

    if total_matches == 0:
        body_lines.append("\n(No keyword matches found.)")
    else:
        body_lines.append("(Full transcript(s) attached.)")

    return "\n".join(body_lines), total_matches


# --- Main ---

def main():
    EMAIL_USER = os.environ["EMAIL_USER"]
    EMAIL_PASS = os.environ["EMAIL_PASS"]
    EMAIL_TO   = os.environ["EMAIL_TO"]

    keywords = load_keywords()
    if not keywords:
        raise SystemExit("No keywords found (keywords.txt or KEYWORDS env var).")

    files = sorted(glob.glob("transcripts/*.txt"))
    if not files:
        raise SystemExit("No transcripts found in transcripts/")

    body, total_hits = build_digest(files, keywords)

    subject = f"Hansard keyword digest — {datetime.now().strftime('%d %b %Y')}"
    to_list = [addr.strip() for addr in re.split(r"[,\s]+", EMAIL_TO) if addr.strip()]

    yag = yagmail.SMTP(
        user=EMAIL_USER,
        password=EMAIL_PASS,
        host="smtp.gmail.com",
        port=587,
        smtp_starttls=True,
        smtp_ssl=False,
    )

    yag.send(
        to=to_list,
        subject=subject,
        contents=body,
        attachments=files,
    )
    print(f"✅ Email sent to {EMAIL_TO} with {len(files)} file(s), {total_hits} match(es).")


if __name__ == "__main__":
    main()
import os
import re
import glob
import yagmail
from pathlib import Path
from datetime import datetime

# --- Helpers ---

def load_keywords():
    """Load keywords from keywords.txt or KEYWORDS env var"""
    if os.path.exists("keywords.txt"):
        with open("keywords.txt", encoding="utf-8") as f:
            return [kw.strip() for kw in f if kw.strip()]
    if "KEYWORDS" in os.environ:
        return [kw.strip() for kw in os.environ["KEYWORDS"].split(",") if kw.strip()]
    return []


def split_paragraphs(text):
    """Split transcript into paragraphs."""
    return re.split(r"\n\s*\n", text)


def detect_speaker(paragraph):
    """Detect speaker name at start of paragraph."""
    first_line = paragraph.strip().split("\n", 1)[0]
    if re.match(r"^(Mr|Ms|Mrs|Hon|Premier)\b", first_line):
        return first_line.strip()
    return None


def extract_matches(text, keywords):
    """Find keyword matches and return structured results."""
    results = []
    paragraphs = split_paragraphs(text)

    for para in paragraphs:
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", para, re.IGNORECASE):
                # Extract 2–3 sentences around keyword
                sentences = re.split(r"(?<=[.!?])\s+", para.strip())
                for i, s in enumerate(sentences):
                    if kw.lower() in s.lower():
                        start = max(0, i - 1)
                        end = min(len(sentences), i + 2)
                        snippet = " ".join(sentences[start:end])
                        speaker = detect_speaker(para)
                        results.append((kw, snippet.strip(), speaker))
                        break
    return results


def parse_date_from_filename(filename):
    """Extract datetime from Hansard filename, e.g. House_of_Assembly_Tuesday_3_June_2025.txt"""
    m = re.search(r"(\d{1,2} \w+ \d{4})", filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%d %B %Y")
        except ValueError:
            return datetime.min
    return datetime.min


def build_digest(files, keywords):
    """Build the digest body text for email."""
    all_matches = []
    body_lines = []

    # Header
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    body_lines.append(f"Time: {now}")
    body_lines.append("Keywords: " + ", ".join(keywords))

    # Process each transcript file
    total_matches = 0
    for f in sorted(files, key=lambda x: parse_date_from_filename(Path(x).name)):
        text = Path(f).read_text(encoding="utf-8", errors="ignore")
        matches = extract_matches(text, keywords)
        if not matches:
            continue
        total_matches += len(matches)

        body_lines.append(f"\n=== {Path(f).name} ===")
        for i, (kw, snippet, speaker) in enumerate(matches, 1):
            if speaker:
                body_lines.append(f"🔹 Match #{i} ({speaker})")
            else:
                body_lines.append(f"🔹 Match #{i}")
            body_lines.append(snippet)
            body_lines.append("")

    body_lines.insert(2, f"Matches found: {total_matches}\n")

    if total_matches == 0:
        body_lines.append("\n(No keyword matches found.)")
    else:
        body_lines.append("(Full transcript(s) attached.)")

    return "\n".join(body_lines), total_matches
