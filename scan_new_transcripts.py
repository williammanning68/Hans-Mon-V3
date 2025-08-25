#!/usr/bin/env python3
"""
Scan Tas Parliament search for latest House of Assembly items,
download any *new* transcripts as TXT, and remember what we've seen.

Env (optional):
  MAX_RESULTS: how many results to scan (default: 10)
  WAIT_BEFORE_DOWNLOAD_SECONDS: delay before clicking Download (default: 15)
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).parent.resolve()
TRANSCRIPTS = ROOT / "transcripts"
STATE_DIR = ROOT / "state"
SEEN_FILE = STATE_DIR / "seen.json"
TRANSCRIPTS.mkdir(exist_ok=True)
STATE_DIR.mkdir(exist_ok=True)

MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "10"))
WAIT_BEFORE = int(os.environ.get("WAIT_BEFORE_DOWNLOAD_SECONDS", "15"))

def sanitize(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._ -]", "_", name).strip()
    safe = re.sub(r"\s+", " ", safe)
    return safe

def load_seen():
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(seen, indent=2, ensure_ascii=False), encoding="utf-8")

def scan_and_download():
    seen = load_seen()
    downloaded = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        print("Opening search home…")
        page.goto("https://search.parliament.tas.gov.au/search/", wait_until="domcontentloaded")
        page.wait_for_selector("#isys_edt_search", timeout=30000)

        # Ensure we search Hansard for House of Assembly
        try:
            page.fill("#isys_edt_search", "AUTHOR CONTAINS (House of Assembly)")
        except PWTimeout:
            pass

        print("Submitting search…")
        page.click("#isys_btn_search_hdr")
        page.wait_for_selector("table.results-table", timeout=30000)

        # Try to sort by Date if the quick link is present
        try:
            page.click("a[href*='/datetime/sort/']", timeout=5000)
            page.wait_for_load_state("networkidle")
            page.wait_for_selector("table.results-table", timeout=10000)
        except Exception:
            pass

        rows = page.locator("table.results-table tr")
        total = rows.count()
        to_check = min(total, MAX_RESULTS)
        print(f"Found {total} results; checking top {to_check}…")

        for i in range(to_check):
            row = rows.nth(i)
            title_link = row.locator("a[onclick^='isys.viewer.show']").first
            docx_link = row.locator("a[id^='isys_var_url_']").first  # "Download Document" link

            try:
                title = title_link.inner_text().strip()
            except Exception:
                continue

            # Prefer a stable key from the docx href if present
            key = None
            try:
                href = docx_link.get_attribute("href")
                if href:
                    key = href  # e.g. /search/isysquery/.../doc/HA Tuesday 19 August 2025.docx
            except Exception:
                pass
            if not key:
                key = title

            safe_title = sanitize(title)
            out_path = TRANSCRIPTS / f"{safe_title}.txt"

            # Skip if already known/seen OR already saved in transcripts/
            if key in seen or out_path.exists():
                print(f"  • Already have: {title}")
                seen[key] = seen.get(key, {"title": title, "saved": "preexisting"})
                continue

            print(f"  • NEW: {title} — opening viewer…")
            title_link.click()
            page.wait_for_selector("#viewer_toolbar", timeout=40000)

            # Give the viewer time to wire up
            page.wait_for_timeout(WAIT_BEFORE * 1000)

            # Open the Download menu
            page.click("#viewer_toolbar .btn.btn-download", timeout=30000)

            # Click "As Text" and save
            page.wait_for_selector("#viewer_toolbar_download li", timeout=20000)
            with page.expect_download() as dl_info:
                page.click("#viewer_toolbar_download li:has-text('As Text')", timeout=20000)
            download = dl_info.value
            download.save_as(out_path)
            print(f"    ✅ Saved: {out_path.name}")

            downloaded.append(str(out_path))
            seen[key] = {
                "title": title,
                "saved": datetime.now(timezone.utc).isoformat()
            }

            # Close viewer
            try:
                page.click("#viewer_toolbar .btn.btn-close", timeout=5000)
                page.wait_for_timeout(300)
            except Exception:
                pass

        save_seen(seen)
        print(f"Done. New downloads this run: {len(downloaded)}")
        if downloaded:
            # Write list for the email step
            (ROOT / "new_files.txt").write_text("\n".join(downloaded), encoding="utf-8")

if __name__ == "__main__":
    scan_and_download()
