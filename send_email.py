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

# Federal Group brand colors (matching official branding)
BRAND_PRIMARY = "#4A5C68"  # Federal Group dark blue-gray
BRAND_GOLD = "#D4AF37"  # Federal Group gold
BRAND_SECONDARY = "#7A8B98"  # Lighter gray for accents
HIGHLIGHT_COLOR = "#FFF3CD"  # Soft yellow for keyword highlighting
TEXT_DARK = "#2C3E50"  # Dark text color


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
    
    return "Unknown Speaker"


def highlight_keywords(text: str, keywords):
    """
    Highlight keywords in HTML with <mark> tags.
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
        # Case-insensitive replacement with highlighting
        pattern = re.compile(r'\b(' + re.escape(kw) + r')\b', re.IGNORECASE)
        text = pattern.sub(
            f'<mark style="background-color: {HIGHLIGHT_COLOR}; color: {TEXT_DARK}; padding: 2px 4px; border-radius: 3px; font-weight: 600; border-bottom: 2px solid {BRAND_GOLD};">\\1</mark>',
            text
        )
    
    return text


def paragraph_digest_html(text: str, keywords, radius=0, max_matches=50):
    """
    Return (digest_html, total_matches, displayed_matches).
    Creates HTML formatted digest with speaker names and highlighted keywords.
    Limits output to max_matches to prevent email size issues.
    """
    paras = split_paragraphs(text)
    if not keywords:
        return "<p>No keywords specified for matching.</p>", 0, 0

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
    
    total_matches = len(unique_matches)
    
    # Limit matches to prevent massive emails
    if total_matches > max_matches:
        unique_matches = unique_matches[:max_matches]
        displayed_matches = max_matches
    else:
        displayed_matches = total_matches

    if not unique_matches:
        return "<p>No keywords matched in this transcript.</p>", 0, 0

    # Build HTML content
    html_parts = []
    
    # Add notice if matches were limited
    if total_matches > max_matches:
        html_parts.append(f'''
            <div style="background-color: #FFF3CD; border: 1px solid {BRAND_GOLD}; 
                        border-radius: 5px; padding: 15px; margin-bottom: 20px;">
                <p style="margin: 0; color: {TEXT_DARK};">
                    <strong>Note:</strong> Found {total_matches} total matches. 
                    Showing first {displayed_matches} to keep email size manageable.
                    Full transcript attached for complete review.
                </p>
            </div>
        ''')
    
    for idx, match in enumerate(unique_matches, 1):
        html_parts.append(f'<div class="match-block" style="margin-bottom: 30px;">')
        html_parts.append(f'''
            <h3 style="color: {BRAND_PRIMARY}; border-left: 4px solid {BRAND_GOLD}; 
                       padding-left: 15px; margin: 20px 0 15px 0; font-weight: 400;">
                Match #{idx}
            </h3>
        ''')
        
        for para in match:
            border_style = f"border-left: 3px solid {BRAND_GOLD};" if para['is_match'] else "border-left: 2px solid #e0e0e0;"
            bg_color = "#fafafa" if not para['is_match'] else "#ffffff"
            html_parts.append(f'''
                <div class="speech" style="{border_style} padding: 15px; margin: 10px 0; background-color: {bg_color}; border-radius: 0 5px 5px 0;">
                    <p style="font-weight: 600; color: {BRAND_PRIMARY}; margin: 0 0 8px 0; font-size: 14px;">
                        <span style="border-bottom: 1px solid {BRAND_GOLD}; padding-bottom: 2px;">
                            {para['speaker']}
                        </span>
                    </p>
                    <p style="margin: 5px 0; line-height: 1.7; color: {TEXT_DARK};">
                        {para['text']}
                    </p>
                </div>
            ''')
        
        html_parts.append('</div>')

    return ''.join(html_parts), total_matches, displayed_matches


def create_html_email(digest_html: str, keywords: list, match_count: int, 
                     transcript_name: str, human_time: str, displayed_count: int = None):
    """
    Create a complete HTML email with Federal Group branding.
    """
    # Use displayed_count if provided, otherwise use match_count
    if displayed_count is None:
        displayed_count = match_count
        
    # Create match display text
    if match_count > displayed_count:
        match_display = f"{match_count} (showing {displayed_count})"
    else:
        match_display = str(match_count)
    
    html_template = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Hansard Transcript Digest</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; 
                 line-height: 1.6; color: {TEXT_DARK}; max-width: 800px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;">
        
        <!-- Header with Federal Group branding -->
        <div style="background-color: {BRAND_PRIMARY}; padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
            <!-- Federal Group logo recreation -->
            <div style="display: inline-block; margin-bottom: 15px;">
                <div style="display: inline-flex; align-items: center;">
                    <div style="width: 45px; height: 45px; border: 2px solid {BRAND_GOLD}; border-radius: 50%; 
                                display: flex; align-items: center; justify-content: center; margin-right: 15px;">
                        <span style="color: {BRAND_GOLD}; font-size: 28px; font-weight: 300; font-style: italic;">F</span>
                    </div>
                    <div style="text-align: left;">
                        <span style="color: white; font-size: 32px; font-weight: 300;">Federal</span><span style="color: {BRAND_GOLD}; font-size: 32px; font-weight: 300;">Group</span>
                    </div>
                </div>
            </div>
            <h1 style="color: white; margin: 20px 0 10px 0; font-size: 24px; font-weight: 400;">
                Hansard Monitor Alert
            </h1>
            <p style="color: {BRAND_GOLD}; margin: 5px 0; font-size: 14px;">
                Tasmania Legislative Council & House of Assembly
            </p>
        </div>
        
        <!-- Summary section -->
        <div style="background-color: white; padding: 25px; border-left: 1px solid #ddd; 
                    border-right: 1px solid #ddd; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: {BRAND_PRIMARY}; margin-top: 0; border-bottom: 2px solid {BRAND_GOLD}; 
                       padding-bottom: 10px; font-weight: 400;">Summary</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 10px 0; color: {BRAND_SECONDARY}; font-weight: 600; width: 30%;"><strong>Document:</strong></td>
                    <td style="padding: 10px 0; color: {TEXT_DARK};">{transcript_name}</td>
                </tr>
                <tr style="background-color: #fafafa;">
                    <td style="padding: 10px 0; color: {BRAND_SECONDARY}; font-weight: 600;"><strong>Processed:</strong></td>
                    <td style="padding: 10px 0; color: {TEXT_DARK};">{human_time}</td>
                </tr>
                <tr>
                    <td style="padding: 10px 0; color: {BRAND_SECONDARY}; font-weight: 600;"><strong>Keywords:</strong></td>
                    <td style="padding: 10px 0;">
                        {', '.join([f'<span style="background-color: {HIGHLIGHT_COLOR}; color: {TEXT_DARK}; padding: 3px 8px; border-radius: 3px; margin-right: 5px; border: 1px solid {BRAND_GOLD}; display: inline-block; margin-bottom: 3px;">{kw}</span>' for kw in keywords])}
                    </td>
                </tr>
                <tr style="background-color: #fafafa;">
                    <td style="padding: 10px 0; color: {BRAND_SECONDARY}; font-weight: 600;"><strong>Matches Found:</strong></td>
                    <td style="padding: 10px 0;">
                        <span style="background-color: {BRAND_GOLD}; color: white; padding: 4px 12px; border-radius: 15px; font-weight: 600;">
                            {match_display}
                        </span>
                    </td>
                </tr>
            </table>
        </div>
        
        <!-- Matches section -->
        <div style="background-color: white; padding: 25px; border-left: 1px solid #ddd; 
                    border-right: 1px solid #ddd; border-bottom: 1px solid #ddd; 
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: {BRAND_PRIMARY}; margin-top: 0; border-bottom: 2px solid {BRAND_GOLD}; 
                       padding-bottom: 10px; font-weight: 400;">Keyword Matches</h2>
            {digest_html}
        </div>
        
        <!-- Footer -->
        <div style="background-color: {BRAND_PRIMARY}; padding: 20px; border-radius: 0 0 10px 10px; 
                    text-align: center;">
            <div style="border-top: 1px solid {BRAND_SECONDARY}; padding-top: 15px; margin-top: 5px;">
                <p style="margin: 5px 0; font-size: 13px; color: white;">
                    This is an automated alert from the Hansard Monitor System
                </p>
                <p style="margin: 5px 0; font-size: 13px; color: {BRAND_GOLD};">
                    Full transcript attached to this email
                </p>
                <p style="margin: 15px 0 5px 0; font-size: 11px; color: {BRAND_SECONDARY};">
                    © {datetime.now().year} <span style="color: white;">Federal</span><span style="color: {BRAND_GOLD};">Group</span> - Hansard Monitoring Service
                </p>
            </div>
        </div>
    </body>
    </html>
    '''
    
    return html_template


def create_plain_text_fallback(keywords: list, match_count: int, 
                              transcript_name: str, human_time: str):
    """
    Create plain text version for email clients that don't support HTML.
    """
    return f"""
═══════════════════════════════════════════════════════════════
                    FEDERAL GROUP
              HANSARD MONITOR ALERT
    Tasmania Legislative Council & House of Assembly
═══════════════════════════════════════════════════════════════

SUMMARY
───────────────────────────────────────────────────────────────
Document:       {transcript_name}
Processed:      {human_time}
Keywords:       {', '.join(keywords)}
Matches Found:  {match_count}

───────────────────────────────────────────────────────────────

Full transcript attached to this email.

═══════════════════════════════════════════════════════════════
This is an automated alert from the Hansard Monitor System
© {datetime.now().year} Federal Group - Hansard Monitoring Service
═══════════════════════════════════════════════════════════════
"""


# -------- Main --------

def main():
    latest = find_latest_txt()
    if not latest:
        print("⚠️ No transcript .txt found (looked in transcripts/ and repo root).")
        return

    with open(latest, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Generate HTML digest with match limit for email size
    MAX_MATCHES_IN_EMAIL = 50  # Adjust based on your needs
    
    try:
        digest_html, total_count, displayed_count = paragraph_digest_html(
            content, KEYWORDS, PARAGRAPH_RADIUS, MAX_MATCHES_IN_EMAIL
        )
        
        # Email metadata
        transcript_name = os.path.basename(latest)
        human_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        
        # Adjust subject based on whether all matches are shown
        if total_count > displayed_count:
            subject = f"Hansard Alert: {total_count} Matches Found (showing {displayed_count}) - {transcript_name}"
        else:
            subject = f"Hansard Alert: {total_count} Keyword Matches - {transcript_name}"
        
        # Create HTML email
        html_email = create_html_email(
            digest_html, KEYWORDS, total_count, transcript_name, human_time, displayed_count
        )
        
        # Save HTML digest as artifact (useful for debugging)
        base = os.path.splitext(transcript_name)[0]
        digest_file = f"digest_{base}.html"
        with open(digest_file, "w", encoding="utf-8") as df:
            df.write(html_email)
        print(f"📄 HTML digest saved to {digest_file}")

        # Send HTML email only (no plain text fallback)
        yag = yagmail.SMTP(EMAIL_USER, EMAIL_PASS)
        
        # Force HTML content type
        yag.send(
            to=EMAIL_TO,
            subject=subject,
            contents=html_email,  # Send only HTML version
            attachments=[latest]  # attach full transcript
        )

        if total_count > displayed_count:
            print(f"✅ Email sent to {EMAIL_TO} with {latest}")
            print(f"   Found {total_count} matches, displayed {displayed_count} in email")
            print(f"   (Full transcript attached for complete review)")
        else:
            print(f"✅ Email sent to {EMAIL_TO} with {latest} and digest ({total_count} matches).")
            
    except Exception as e:
        print(f"❌ Error processing email: {str(e)}")
        print(f"   Attempting to send basic notification...")
        
        # If HTML processing fails, send a simple notification
        try:
            yag = yagmail.SMTP(EMAIL_USER, EMAIL_PASS)
            basic_message = f"""
            <html>
            <body>
                <h2>Hansard Monitor Alert</h2>
                <p>A new Hansard transcript is available but the digest generation encountered an issue.</p>
                <p><strong>Document:</strong> {os.path.basename(latest)}</p>
                <p><strong>Keywords monitored:</strong> {', '.join(KEYWORDS)}</p>
                <p><strong>Error:</strong> {str(e)}</p>
                <p>The full transcript is attached for manual review.</p>
            </body>
            </html>
            """
            yag.send(
                to=EMAIL_TO,
                subject=f"Hansard Alert: {os.path.basename(latest)} (Processing Error)",
                contents=basic_message,
                attachments=[latest]
            )
            print(f"✅ Basic notification sent with transcript attached")
        except Exception as e2:
            print(f"❌ Failed to send email: {str(e2)}")


if __name__ == "__main__":
    main()
