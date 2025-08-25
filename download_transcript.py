#!/usr/bin/env python3
"""
download_transcript.py

Scrape the Tasmanian Parliament Hansard "Quick Search" for a given term (defaults to
the current year in Australia/Hobart), download **all** matching transcripts as text,
sort them into chamber folders, and (optionally) send an email **only if** at least
one brand-new transcript was saved (i.e., not already present in the repository).

Requires: playwright
    pip install playwright
    playwright install chromium

Environment variables (all optional unless noted):
  TZ_NAME="Australia/Hobart"   # timezone used when deriving the default year
  WAIT_BEFORE_DOWNLOAD_SECONDS="12"  # pause before opening the download menu in viewer
  MAX_PAGES="50"               # maximum search result pages to traverse
  HEADLESS="1"                 # "1" = headless (default), "0" = show browser (debug)
  SEND_EMAIL_IF_NEW="1"        # "1" to run send_email.py if we saved any new files
  TRANSCRIPTS_DIR="transcripts"  # root folder for saved files
  INDEX_PATH="transcripts/index.json"  # where we track seen doc IDs

Usage:
  python download_transcript.py                # searches for current year (e.g. "2025")
  python download_transcript.py "care homes"   # searches for custom phrase
"""

from __future__ import annotations
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Iterable, List, Optional, Set
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Page, BrowserContext

# ---------------- Configuration helpers ----------------

ROOT = Path(__file__).parent.resolve()
TRANSCRIPTS_DIR = Path(os.environ.get("TRANSCRIPTS_DIR", "transcripts"))
INDEX_PATH = Path(os.environ.get("INDEX_PATH", str(TRANSCRIPTS_DIR / "index.json")))
WAIT_BEFORE_DOWNLOAD = int(os.environ.get("WAIT_BEFORE_DOWNLOAD_SECONDS", "12"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "50"))
TZ_NAME = os.environ.get("TZ_NAME", "Australia/Hobart")
HEADLESS = os.environ.get("HEADLESS", "1") != "0"
SEND_EMAIL_IF_NEW = os.environ.get("SEND_EMAIL_IF_NEW", "1") == "1"

CHAMBER_DIRS = {
    "House of Assembly": TRANSCRIPTS_DIR / "House_of_Assembly",
    "Legislative Council": TRANSCRIPTS_DIR / "Legislative_Council",
    "Other Hansard": TRANSCRIPTS_DIR / "Other_Hansard",
}

for p in CHAMBER_DIRS.values():
    p.mkdir(parents=True, exist_ok=True)
INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

def default_query() -> str:
    tz = ZoneInfo(TZ_NAME)
    return str(datetime.now(tz=tz).year)

def slugify(text: str, maxlen: int = 120) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^A-Za-z0-9._-]+", "", text)
    return text[:maxlen] if maxlen else text

# ---------------- Seen-index handling ----------------

def load_seen_index() -> dict:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_seen_index(idx: dict) -> None:
    tmp = INDEX_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(INDEX_PATH)

# ---------------- Chamber classification ----------------

def detect_chamber(text: str) -> str:
    t = text.lower()
    if "house of assembly" in t or "house_of_assembly" in t or "house—of—assembly" in t:
        return "House of Assembly"
    if "legislative council" in t or "legislative_council" in t:
        return "Legislative Council"
    return "Other Hansard"

# ---------------- Result parsing ----------------

DOC_HREF_RE = re.compile(r"/doc/([^/?#]+)")

def extract_doc_id(href: str) -> Optional[str]:
    m = DOC_HREF_RE.search(href)
    return m.group(1) if m else None

# Collect unique /doc/ links on the current results page
def collect_doc_links_on_page(page: Page) -> list[tuple[str, str]]:
    # returns list of (href, title_text)
    links = page.query_selector_all('a[href*="/doc/"]')
    out = []
    seen = set()
    for a in links:
        href = a.get_attribute("href") or ""
        docid = extract_doc_id(href) or href
        if docid in seen:
            continue
        seen.add(docid)
        title = a.inner_text().strip()
        out.append((href, title))
    return out

def has_next_page(page: Page) -> bool:
    # Try several patterns for "Next" controls
    selectors = [
        'a[rel="next"]',
        'a:has-text("Next")',
        'a:has-text("next")',
        'button:has-text("Next")',
        'button[aria-label="Next"]',
        'li.pagination-next a',
    ]
    for sel in selectors:
        if page.locator(sel).count() > 0:
            return True
    return False

def click_next(page: Page) -> bool:
    selectors = [
        'a[rel="next"]',
        'a:has-text("Next")',
        'a:has-text("next")',
        'button:has-text("Next")',
        'button[aria-label="Next"]',
        'li.pagination-next a',
    ]
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count():
            try:
                loc.first.click()
                return True
            except Exception:
                pass
    return False

# ---------------- Download a single doc ----------------

def download_text_for_doc(page: Page, href: str, title_text: str, context: BrowserContext, out_dir: Path, docid: str) -> Optional[Path]:
    # Open result in same tab
    page.click(f'a[href="{href}"]')
    # Wait for viewer
    try:
        page.wait_for_selector('#viewer_toolbar, [id*="viewer"]', timeout=45000)
    except PWTimeout:
        print(f"  ! Viewer toolbar not found for {docid}. Skipping.")
        return None

    # Give time for the menu to initialize, then open the download menu
    sleep(WAIT_BEFORE_DOWNLOAD)
    # Try several menu openers
    candidates = [
        'div[onclick*="downloadMenu"]',
        '[id*="downloadMenu"]',
        'button:has-text("Download")',
        '#download',
        'button[title*="Download"]'
    ]
    opened = False
    for sel in candidates:
        try:
            if page.locator(sel).count():
                page.locator(sel).first.click()
                opened = True
                break
        except Exception:
            pass
    if not opened:
        print(f"  ! Could not open download menu for {docid}.")
        return None

    # Click "As Text"
    try:
        page.wait_for_selector('li:has-text("As Text"), a:has-text("As Text"), button:has-text("As Text")', timeout=30000)
        with page.expect_download(timeout=45000) as dl:
            page.locator('li:has-text("As Text"), a:has-text("As Text"), button:has-text("As Text")').first.click()
        download = dl.value
    except PWTimeout:
        print(f"  ! 'As Text' option not found for {docid}.")
        return None

    # Save to a temp location, read it, classify, then move
    suggested = download.suggested_filename or f"{slugify(title_text)}.txt"
    temp_path = out_dir / f"__tmp__{slugify(docid)}_{slugify(suggested)}"
    download.save_as(str(temp_path))

    try:
        text = temp_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = temp_path.read_bytes().decode("utf-8", errors="ignore")

    chamber = detect_chamber(text)
    dest_dir = CHAMBER_DIRS[chamber]
    # Final filename: Chamber + slug(title) + docid to guarantee uniqueness
    final_name = f"{slugify(chamber)}__{slugify(title_text)}__{slugify(docid)}.txt"
    final_path = dest_dir / final_name
    temp_path.replace(final_path)
    print(f"  ✓ Saved: {final_path.relative_to(ROOT)}")
    return final_path

# ---------------- Main flow ----------------

def run(query: Optional[str] = None) -> int:
    search_term = (query or "").strip() or default_query()
    print(f"🔎 Searching Hansard Quick Search for: {search_term!r}")

    seen_index = load_seen_index()  # {docid: saved_path_str}
    seen_ids: Set[str] = set(seen_index.keys())
    new_saves: list[Path] = []

    hansard_page = "https://www.parliament.tas.gov.au/hansard"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # Go to landing page and submit Quick Search
        page.goto(hansard_page, wait_until="domcontentloaded")
        try:
            page.wait_for_selector('form#queryForm input[name="IW_FIELD_ADVANCE_PHRASE"]', timeout=30000)
        except PWTimeout:
            print("❌ Could not find Quick Search input on the Hansard landing page.")
            browser.close()
            return 2

        page.fill('form#queryForm input[name="IW_FIELD_ADVANCE_PHRASE"]', search_term)
        page.keyboard.press("Enter")

        # Wait for some results to show
        try:
            page.wait_for_selector('a[href*="/doc/"]', timeout=35000)
        except PWTimeout:
            print(f"⚠️ No results found for {search_term!r}.")
            browser.close()
            return 0

        # Iterate across pages
        current_page = 1
        while True:
            print(f"\n--- Results page {current_page} ---")
            doc_links = collect_doc_links_on_page(page)
            print(f"  Found {len(doc_links)} doc links on this page.")

            for href, title_text in doc_links:
                docid = extract_doc_id(href) or href
                if docid in seen_ids:
                    # Already downloaded in a past run
                    continue

                print(f"→ Processing doc {docid} : {title_text[:80]}")
                path = download_text_for_doc(page, href, title_text, context, ROOT, docid)
                # Navigate back to results list
                page.go_back(wait_until="domcontentloaded")
                try:
                    page.wait_for_selector('a[href*="/doc/"]', timeout=25000)
                except PWTimeout:
                    pass

                if path:
                    seen_index[docid] = str(path.relative_to(ROOT))
                    seen_ids.add(docid)
                    new_saves.append(path)

            # Pagination
            if current_page >= MAX_PAGES:
                print(f"⏹ Reached MAX_PAGES={MAX_PAGES}.")
                break
            if not has_next_page(page):
                break
            if not click_next(page):
                break

            # Wait for next page results
            try:
                page.wait_for_selector('a[href*="/doc/"]', timeout=30000)
            except PWTimeout:
                print("⚠️ Next page did not load expected results. Stopping.")
                break
            current_page += 1

        browser.close()

    # Persist index
    save_seen_index(seen_index)

    # Summary & optional email
    if new_saves:
        print(f"\n✅ New transcripts saved this run: {len(new_saves)}")
        for pth in new_saves:
            print(f"   - {pth.relative_to(ROOT)}")

        if SEND_EMAIL_IF_NEW:
            send_email_path = ROOT / "send_email.py"
            if send_email_path.exists():
                print("📧 Sending email (because new transcripts were found)...")
                # Run a separate process so send_email.py can own its env & imports
                import subprocess, sys as _sys
                try:
                    subprocess.run([_sys.executable, str(send_email_path)], check=True)
                except Exception as e:
                    print(f"   ! Email step failed: {e}")
            else:
                print("   ! send_email.py not found; skipping email step.")
        return 0
    else:
        print("\nNo new transcripts were found (nothing to email).")
        return 0

# ---------------- Entry ----------------

if __name__ == "__main__":
    arg = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else None
    raise SystemExit(run(arg))
