#!/usr/bin/env python3
"""
Scan Tas Parliament Hansard 'Quick Search' for new transcripts this year
and download any not already in the repository, split by House.

Outputs:
  transcripts/assembly/House_of_Assembly_<Date>.txt
  transcripts/council/Legislative_Council_<Date>.txt

Env (optional):
  YEAR=2025          # default: current year
  MAX_PAGES=5        # how many result pages to scan
"""

import os
import re
import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_SEARCH = "https://search.parliament.tas.gov.au/Search/search/search"

# Quick Search parameters (from the Hansard page source):
#   - IW_FIELD_ADVANCE_PHRASE: the query string (we use the year)
#   - IW_DATABASE: Hansard
#   - IW_SORT: -9 (newest first)
#   - IW_PAGE: page number (1-based)
def build_search_url(year: int, page_num: int) -> str:
    params = {
        "IW_FIELD_ADVANCE_PHRASE": str(year),
        "IW_DATABASE": "Hansard",
        "IW_SORT": "-9",
        "IW_PAGE": str(page_num),
    }
    return f"{BASE_SEARCH}?{urlencode(params)}"

ROOT = Path(__file__).parent.resolve()
OUT_ASSEMBLY = ROOT / "transcripts" / "assembly"
OUT_COUNCIL  = ROOT / "transcripts" / "council"
for d in (OUT_ASSEMBLY, OUT_COUNCIL):
    d.mkdir(parents=True, exist_ok=True)

FILENAME_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")

def safe_name(s: str) -> str:
    return FILENAME_SAFE.sub("_", s).strip("_")

def which_house(title: str) -> str | None:
    t = title.strip()
    if "House of Assembly" in t:
        return "assembly"
    if "Legislative Council" in t:
        return "council"
    return None

def container_title_text(page, container):
    """Try to read the display title from a search-result container."""
    # Get the first link in the container that is NOT the "TXT" helper.
    links = container.locator("a").filter(has_not_text="TXT")
    if links.count() == 0:
        # Fallback: maybe the container text itself contains the title
        return container.inner_text().splitlines()[0].strip()
    return links.first.inner_text().strip()

def download_from_txt_link(page, txt_link, out_path: Path) -> bool:
    """Click the TXT link with expect_download and save to out_path."""
    try:
        with page.expect_download() as dl_info:
            txt_link.click()
        download = dl_info.value
        download.save_as(out_path)
        return True
    except Exception:
        return False

def scan_page(page, out_counts: dict[str, int]) -> int:
    """
    Scan the current results page for TXT links, categorize by House,
    download if missing. Returns number of new files on this page.
    """
    new_on_page = 0

    # Ensure results have rendered some TXT links; if none after a wait, nothing to do.
    try:
        page.wait_for_selector("a:has-text('TXT')", timeout=15000)
    except PWTimeout:
        return 0

    txt_links = page.locator("a:has-text('TXT')")
    n = txt_links.count()
    for i in range(n):
        txt = txt_links.nth(i)
        # Find a container for this result row (works for table/div/li variants).
        container = txt.locator("xpath=ancestor::tr | ancestor::div[contains(@class,'result')] | ancestor::li")
        if container.count() == 0:
            # Fallback: just use the txt link's previous sibling context
            container = txt.locator("xpath=ancestor::*[1]")

        title = container_title_text(page, container)
        house = which_house(title)
        if not house:
            continue

        # Compose target dir & filename (keep original house words in filename)
        base_filename = f"{safe_name(title)}.txt"
        out_dir = OUT_ASSEMBLY if house == "assembly" else OUT_COUNCIL
        out_path = out_dir / base_filename

        if out_path.exists():
            continue  # already have it

        # Try the fast TXT download route
        ok = download_from_txt_link(page, txt, out_path)
        if ok:
            print(f"   ✅ Saved: {out_path.relative_to(ROOT)}")
            out_counts[house] = out_counts.get(house, 0) + 1
            new_on_page += 1
        else:
            print(f"   ⚠️  TXT download failed for: {title}")

    return new_on_page

def main():
    year = int(os.getenv("YEAR") or datetime.now().year)
    max_pages = int(os.getenv("MAX_PAGES") or "5")

    print(f"\nYear = {year}")
    print(f"Max pages to scan = {max_pages}")
    print(f"Transcripts root = {ROOT/'transcripts'}")

    totals = {"assembly": 0, "council": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()

        # One pass over pages; we’ll filter per House from the titles
        for page_num in range(1, max_pages + 1):
            url = build_search_url(year, page_num)
            print(f"\nScanning results page {page_num}…")
            page.goto(url, wait_until="domcontentloaded")

            # If there are zero TXT links after a short wait, assume no more pages.
            try:
                page.wait_for_selector("a:has-text('TXT')", timeout=8000)
            except PWTimeout:
                print("No TXT links found on this page — stopping.")
                break

            new_here = scan_page(page, totals)
            # If zero new on this page but there were results, keep going —
            # older pages might still have missing items on a fresh repo.

        browser.close()

    new_total = totals.get("assembly", 0) + totals.get("council", 0)
    print("\nDone.")
    print(f"New downloads this run: {new_total} "
          f"(Assembly: {totals.get('assembly',0)}, Council: {totals.get('council',0)})")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
