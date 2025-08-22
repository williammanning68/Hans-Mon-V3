#!/usr/bin/env python3
"""
Download a Hansard transcript from the Tasmanian Parliament search site.

Usage:
    python download_transcript.py "House of Assembly Tuesday 19 August 2025"
"""
import os
import re
import sys
from pathlib import Path
from time import sleep

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).parent.resolve()
OUT_DIR = ROOT / "transcripts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

WAIT_BEFORE_DOWNLOAD = int(os.environ.get("WAIT_BEFORE_DOWNLOAD_SECONDS", "15"))

def sanitise_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name) + ".txt"

def download_transcript(query: str) -> None:
    url = "https://search.parliament.tas.gov.au/adv/hahansard"
    out_path = OUT_DIR / sanitise_filename(query)

    with sync_playwright() as p:
        # Headless for GitHub Actions
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # Open advanced search page
        page.goto(url, wait_until="domcontentloaded")

        # Type into the correct search box and submit
        page.wait_for_selector('input[name="IW_FIELD_TERM"]', timeout=20000)
        page.fill('input[name="IW_FIELD_TERM"]', query)
        page.keyboard.press("Enter")

        # Wait for results (anchors that open documents)
        try:
            page.wait_for_selector('a[href*="/doc/"]', timeout=20000)
        except PWTimeout:
            print("No results found for that term.")
            browser.close()
            return

        # Open the first result to load the viewer
        page.click('a[href*="/doc/"]')

        # Wait for the viewer toolbar to appear
        page.wait_for_selector('#viewer_toolbar', timeout=40000)

        # Allow extra time for UI to finish wiring up
        sleep(WAIT_BEFORE_DOWNLOAD)

        # Open the download menu
        page.click('div[onclick*="downloadMenu"]')

        # Click "As Text" and wait for download event
        page.wait_for_selector('li:has-text("As Text")', timeout=40000)
        with page.expect_download() as dl:
            page.click('li:has-text("As Text")')
        download = dl.value

        # Save to transcripts/ folder
        download.save_as(str(out_path))
        print(f"Saved to {out_path}")

        browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: download_transcript.py "SEARCH QUERY"')
        sys.exit(1)
    download_transcript(sys.argv[1])
