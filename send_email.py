#!/usr/bin/env python3
"""
Email the latest downloaded Hansard transcript, plus a keyword digest.
Enhanced with HTML formatting, speaker identification, and keyword highlighting.

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
from html import escape

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
    return [p.strip() for p in re.split(r"\r?\n\s*\r?\n", text) if p.strip()]


def extract_speaker(paragraph: str):
    """
    Extract speaker name from Hansard format.
    Common patterns: "MR SMITH:", "Ms Jones:", "The PRESIDENT:", etc.
    """
    # Pattern for typical Hansard speaker format
    patterns = [
        r'^((?:Mr|Mrs|Ms|Miss|Dr|Prof|The)\s+[A-Z][A-Za-z\s\-\']+?)[\s:]+',
        r'^([A-Z][A-Z\s\-\']+?)[\s:]+',  # All caps name
        r'^((?:PRESIDENT|SPEAKER|CHAIR|DEPUTY))[\s:]+',  # Positions
    ]
    
    for pattern in patterns:
        match = re.match(pattern, paragraph)
        if match:
            return match.group(1).strip().title()
    
    return ""  # Return empty string if no speaker found


def highlight_keywords(text: str, keywords):
    """
    Highlight keywords in HTML with subtle styling.
    Preserves HTML escaping for safety.
    """
    # First escape HTML
    text = escape(text)
    
    # Create pattern for whole-word matching
    if not keywords:
        return text
    
    # Sort keywords by length (longest first) to handle overlapping matches
    sorted_kws = sorted(keywords, key=len, reverse=True)
    
    for kw in sorted_kws:
        # Case-insensitive replacement with subtle highlighting
        pattern = re.compile(r'\b(' + re.escape(kw) + r')\b', re.IGNORECASE)
        text = pattern.sub(
            '<strong style="background-color: #FFFACD; padding: 0 2px;">\\1</strong>',
            text
        )
    
    return text


def paragraph_digest_html(text: str, keywords, radius=0):
    """
    Return (digest_html, num_matches).
    Creates HTML formatted digest with speaker names and highlighted keywords.
    """
    paras = split_paragraphs(text)
    if not keywords:
        return "<p>No keywords specified for matching.</p>", 0

    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
                         re.IGNORECASE)

    matches = []
    for i, p in enumerate(paras):
        if pattern.search(p):
            start = max(0, i - radius)
            end = min(len(paras), i + radius + 1)
            
            # Collect context paragraphs
            context_paras = []
            for j in range(start, end):
                speaker = extract_speaker(paras[j])
                highlighted = highlight_keywords(paras[j], keywords)
                context_paras.append({
                    'speaker': speaker,
                    'text': highlighted,
                    'is_match': (j == i)
                })
            
            matches.append(context_paras)

    # Deduplicate matches
    unique_matches = []
    seen = set()
    for match in matches:
        match_key = tuple((p['text'] for p in match))
        if match_key not in seen:
            unique_matches.append(match)
            seen.add(match_key)

    if not unique_matches:
        return "<p>No keywords matched in this transcript.</p>", 0

    # Build compact HTML content
    html_parts = []
    for idx, match in enumerate(unique_matches, 1):
        html_parts.append(f'<div style="margin-bottom: 20px;">')
        html_parts.append(f'<p style="color: #666; font-size: 12px; margin: 0 0 8px 0;">Match {idx}</p>')
        
        for para in match:
            if para['speaker']:
                html_parts.append(f'''
                    <div style="margin: 8px 0;">
                        <span style="font-weight: 600; color: #333; font-size: 13px;">{para['speaker']}:</span>
                        <span style="color: #333; font-size: 13px; line-height: 1.5;">
                            {para['text']}
                        </span>
                    </div>
                ''')
            else:
                # No speaker identified - just show the text
                html_parts.append(f'''
                    <div style="margin: 8px 0; color: #333; font-size: 13px; line-height: 1.5;">
                        {para['text']}
                    </div>
                ''')
        
        html_parts.append('</div>')

    return ''.join(html_parts), len(unique_matches)


def create_html_email(digest_html: str, keywords: list, match_count: int, 
                     transcript_name: str, human_time: str):
    """
    Create a refined, elegant HTML email with subtle Federal Group branding.
    """
    
    html_template = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Hansard Digest</title>
    </head>
    <body style="font-family: Georgia, 'Times New Roman', serif; color: #333; max-width: 650px; margin: 20px auto; padding: 0; background-color: #fff;">
        
        <!-- Header -->
        <div style="border-bottom: 1px solid #e0e0e0; padding-bottom: 15px; margin-bottom: 20px;">
            <h1 style="font-size: 18px; font-weight: normal; margin: 0; color: #333;">
                Federal Group | Hansard Monitor
            </h1>
            <p style="font-size: 12px; color: #666; margin: 5px 0 0 0;">
                Tasmania Legislative Council & House of Assembly
            </p>
        </div>
        
        <!-- Summary -->
        <div style="margin-bottom: 25px;">
            <table style="width: 100%; font-size: 13px; line-height: 1.8;">
                <tr>
                    <td style="width: 100px; color: #666; vertical-align: top;">Document:</td>
                    <td style="color: #333;">{transcript_name}</td>
                </tr>
                <tr>
                    <td style="color: #666; vertical-align: top;">Date:</td>
                    <td style="color: #333;">{human_time}</td>
                </tr>
                <tr>
                    <td style="color: #666; vertical-align: top;">Keywords:</td>
                    <td style="color: #333;">{', '.join(keywords)}</td>
                </tr>
                <tr>
                    <td style="color: #666; vertical-align: top;">Matches:</td>
                    <td style="color: #333;"><strong>{match_count}</strong></td>
                </tr>
            </table>
        </div>
        
        <!-- Divider -->
        <div style="border-bottom: 1px solid #e0e0e0; margin-bottom: 20px;"></div>
        
        <!-- Matches -->
        <div style="margin-bottom: 30px;">
            {digest_html}
        </div>
        
        <!-- Footer -->
        <div style="border-top: 1px solid #e0e0e0; padding-top: 15px; margin-top: 30px;">
            <p style="font-size: 11px; color: #999; margin: 0; text-align: center;">
                Full transcript attached | Automated Hansard Monitor System
            </p>
        </div>
    </body>
    </html>
    '''
    
    return html_template


# -------- Main --------

def main():
    latest = find_latest_txt()
    if not latest:
        print("⚠️ No transcript .txt found (looked in transcripts/ and repo root).")
        return

    with open(latest, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    try:
        # Generate HTML digest - no limits
        digest_html, count = paragraph_digest_html(content, KEYWORDS, PARAGRAPH_RADIUS)
        
        # Email metadata
        transcript_name = os.path.basename(latest)
        human_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        subject = f"Hansard: {count} matches - {transcript_name}"
        
        # Create HTML email
        html_email = create_html_email(
            digest_html, KEYWORDS, count, transcript_name, human_time
        )
        
        # Save HTML digest for debugging
        base = os.path.splitext(transcript_name)[0]
        digest_file = f"digest_{base}.html"
        with open(digest_file, "w", encoding="utf-8") as df:
            df.write(html_email)
        print(f"📄 HTML digest saved to {digest_file}")

        # Send HTML email
        yag = yagmail.SMTP(EMAIL_USER, EMAIL_PASS)
        yag.send(
            to=EMAIL_TO,
            subject=subject,
            contents=html_email,
            attachments=[latest]
        )

        print(f"✅ Email sent to {EMAIL_TO} with {count} matches.")
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        
        # Send basic notification on error
        try:
            yag = yagmail.SMTP(EMAIL_USER, EMAIL_PASS)
            basic_message = f"""
            <html>
            <body style="font-family: Georgia, serif; color: #333;">
                <h2 style="font-size: 16px;">Hansard Monitor Alert</h2>
                <p>Document: {os.path.basename(latest)}</p>
                <p>Error processing digest. Full transcript attached.</p>
            </body>
            </html>
            """
            yag.send(
                to=EMAIL_TO,
                subject=f"Hansard: {os.path.basename(latest)}",
                contents=basic_message,
                attachments=[latest]
            )
            print(f"✅ Basic notification sent")
        except Exception as e2:
            print(f"❌ Failed to send: {str(e2)}")


if __name__ == "__main__":
    main()
