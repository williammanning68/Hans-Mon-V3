#!/usr/bin/env python3
"""
scan_new_transcripts.py (Quick Search version)

- Opens https://www.parliament.tas.gov.au/hansard
- Uses the on-page "Quick Search" to search by current year (e.g. 2025)
- On the search results site, iterates result pages, and for each house:
    * House of Assembly
    * Legislative Council
  finds results whose title starts with that house prefix and downloads "As Text"
  via the built-in viewer, saving them into separate folders:
    transcripts/House_of_Assembly/
    transcripts/Legislative_Council/

Environment variables (optional):
  MAX_PAGES_PER_HOUSE            default "5"
  WAIT_BEFORE_DOWNLOAD_SECONDS   default "15"
  YEAR_OVERRIDE                  set a specific year (e.g. "2024") instead of current
"""
import os
import re
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).parent.resolve()
TRANSCRIPTS_ROOT = ROOT / "transcripts"
HOA_DIR = TRANSCRIPTS_ROOT / "House_of_Assembly"
LC_DIR = TRANSCRIPTS_ROOT / "Legislative_Council"
for d in (TRANSCRIPTS_ROOT, HOA_DIR, LC_DIR):
    d.mkdir(parents=True, exist_ok=True)

MAX_PAGES_PER_HOUSE = int(os.getenv("MAX_PAGES_PER_HOUSE", "5"))
WAIT_BEFORE_DOWNLOAD = float(os.getenv("WAIT_BEFORE_DOWNLOAD_SECONDS", "15"))

def current_year() -> int:
    y = os.getenv("YEAR_OVERRIDE")
    if y and y.isdigit():
        return int(y)
    return datetime.now(timezone.utc).astimezone().year

def sanitize_filename(title: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._()-]+", "_", title.strip())
    s = re.sub(r"_+", "_", s)
    return s + ".txt"

def find_quick_search_input(page) -> Optional[str]:
    """Try a bunch of selectors likely to be the Hansard 'Quick Search' input."""
    candidates = [
        "input#query",
        "input[name='query']",
        "input[name='keys']",
        "input[placeholder*='Quick']",
        "input[placeholder*='Search']",
        "input[type='search']",
        "#isys_edt_search",  # fallback: search site header
    ]
    for sel in candidates:
        try:
            page.wait_for_selector(sel, timeout=4000, state="visible")
            return sel
        except PWTimeout:
            continue
    return None

def open_hansard_and_search(page, year: int):
    url = "https://www.parliament.tas.gov.au/hansard"
    print(f"Opening Hansard home… ({url})", flush=True)
    page.goto(url, wait_until="domcontentloaded")
    sel = find_quick_search_input(page)
    if sel is None:
        # Fallback: go straight to search site home which has the header search
        url2 = "https://search.parliament.tas.gov.au/search/"
        print(f"Quick Search not found; falling back to {url2}", flush=True)
        page.goto(url2, wait_until="domcontentloaded")
        sel = find_quick_search_input(page)
        if sel is None:
            raise RuntimeError("Could not find a search input on Hansard or Search site")
    page.fill(sel, str(year))
    page.keyboard.press("Enter")
    wait_for_results(page)

def wait_for_results(page):
    """Wait until search results list is visible on 'search.parliament.tas.gov.au'"""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except PWTimeout:
        pass
    for sel in ["table.results-table", "a[href*='/doc/']"]:
        try:
            page.wait_for_selector(sel, timeout=15000, state="visible")
            return
        except PWTimeout:
            continue
    raise RuntimeError("Search results did not appear.")

def collect_results_on_page(page) -> List[Tuple[str, str]]:
    """Return list of (title_text, href) for doc entries on the current results page."""
    items = []
    links = page.locator("a[href*='/doc/']")
    for i in range(links.count()):
        a = links.nth(i)
        title = a.inner_text(timeout=2000).strip()
        href = a.get_attribute("href") or ""
        if not href:
            continue
        title = re.sub(r"\s+", " ", title)
        items.append((title, href))
    return items

def open_result_in_viewer(page, href: str):
    if href.startswith("/"):
        url = "https://search.parliament.tas.gov.au" + href
    else:
        url = href
    page.click(f"a[href='{href}']")
    page.wait_for_selector("#viewer_toolbar .btn.btn-download, .btn.btn-original",
                           timeout=20000, state="visible")

def download_as_text_from_viewer(page, save_path: Path) -> bool:
    """Click Download -> 'As Text' and save. Return True if downloaded; False if failed."""
    try:
        print(f"   Waiting {int(WAIT_BEFORE_DOWNLOAD)}s before download…", flush=True)
        time.sleep(WAIT_BEFORE_DOWNLOAD)
        if page.locator("#viewer_toolbar .btn.btn-download").count():
            page.click("#viewer_toolbar .btn.btn-download")
            page.wait_for_selector("#viewer_toolbar_download li", timeout=15000, state="visible")
            targets = [
                "#viewer_toolbar_download li:has-text('As Text')",
                "#viewer_toolbar_download li:has-text('Text')",
            ]
            for t in targets:
                if page.locator(t).count():
                    with page.expect_download(timeout=30000) as dl:
                        page.click(t)
                    download = dl.value
                    download.save_as(str(save_path))
                    return True
            if page.locator("#viewer_toolbar_download li:has-text('As PDF')").count():
                with page.expect_download(timeout=30000) as dl:
                    page.click("#viewer_toolbar_download li:has-text('As PDF')")
                download = dl.value
                download.save_as(str(save_path.with_suffix(".pdf")))
                return True
        if page.locator("#viewer_toolbar .btn.btn-original").count():
            with page.expect_download(timeout=30000) as dl:
                page.click("#viewer_toolbar .btn.btn-original")
            download = dl.value
            download.save_as(str(save_path))
            return True
    except PWTimeout:
        return False
    return False

def close_viewer_if_open(page):
    if page.locator("#viewer_toolbar .btn.btn-close").count():
        try:
            page.click("#viewer_toolbar .btn.btn-close")
            page.wait_for_selector("#viewer_toolbar", state="hidden", timeout=5000)
        except PWTimeout:
            pass

def next_results_page(page) -> bool:
    """Click 'Next >' if present; return True if navigated, False if no more."""
    if page.locator("#isys_var_nextbatch").count():
        page.click("#isys_var_nextbatch")
        wait_for_results(page)
        return True
    locator = page.locator("a:has-text('Next')")
    if locator.count():
        locator.first.click()
        wait_for_results(page)
        return True
    return False

def scan_house(page, house_prefix: str, dest_dir: Path) -> List[Path]:
    """Iterate pages, download missing items for a given House. Returns new files saved."""
    saved: List[Path] = []
    page_num = 1
    print(f"Scanning results page {page_num}…", flush=True)
    while True:
        items = collect_results_on_page(page)
        house_items = [(t, h) for (t, h) in items if t.startswith(house_prefix)]
        for title, href in house_items:
            basename = sanitize_filename(title)
            out_path = dest_dir / basename
            if out_path.exists():
                continue
            print(f"→ Opening: {title}", flush=True)
            open_result_in_viewer(page, href)
            ok = download_as_text_from_viewer(page, out_path)
            close_viewer_if_open(page)
            if ok and out_path.exists():
                print(f"   ✅ Saved: {out_path.name}", flush=True)
                saved.append(out_path)
            else:
                print(f"   ⚠️  Failed to download: {title}", flush=True)
        if page_num >= MAX_PAGES_PER_HOUSE:
            break
        if not next_results_page(page):
            break
        page_num += 1
        print(f"Scanning results page {page_num}…", flush=True)
    return saved

def main():
    year = current_year()
    print(f"Year = {year}", flush=True)
    print(f"Max pages per House = {MAX_PAGES_PER_HOUSE}", flush=True)
    print(f"Transcripts root = {TRANSCRIPTS_ROOT}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()

        # Start from Hansard + Quick Search
        open_hansard_and_search(page, year)

        # Scan House of Assembly first
        print("=== House of Assembly ===", flush=True)
        new_hoa = scan_house(page, "House of Assembly", HOA_DIR)

        # Return to first results page by searching again
        open_hansard_and_search(page, year)

        # Scan Legislative Council
        print("=== Legislative Council ===", flush=True)
        new_lc = scan_house(page, "Legislative Council", LC_DIR)

        total = len(new_hoa) + len(new_lc)
        print(f"Done. New downloads this run: {total}", flush=True)

        summary = ROOT / "scan_summary.txt"
        lines = []
        if new_hoa:
            lines.append("[House of Assembly]")
            lines += [f"- {p.name}" for p in new_hoa]
        if new_lc:
            lines.append("[Legislative Council]")
            lines += [f"- {p.name}" for p in new_lc]
        summary.write_text("\n".join(lines), encoding="utf-8")

        ctx.close()
        browser.close()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
