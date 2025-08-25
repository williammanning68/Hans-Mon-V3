#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scan Tasmanian Parliament Hansard for the current year, for BOTH Houses:
  - House of Assembly
  - Legislative Council

Downloads any transcripts not yet in the repository as TXT into separate
subfolders under ./transcripts, and produces a single combined keyword digest
(organized by House) for the new files only.

Environment (all optional):
  WAIT_BEFORE_DOWNLOAD_SECONDS   default: 15
  MAX_PAGES                      default: 5    (per House)
  YEAR                           default: current year in Australia/Hobart

GitHub Actions Outputs:
  new_downloads                  total integer count across both Houses
  digest_path                    path to combined digest file (when created)
"""

import os
import re
import json
import time
import textwrap
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ----------------- paths -----------------
ROOT = Path(__file__).parent.resolve()
TRANSCRIPTS_ROOT = ROOT / "transcripts"
DIGEST_DIR = ROOT / "digests"
KEYWORDS_FILE = ROOT / "keywords.txt"
MANIFEST_FILE = ROOT / ".last_run_manifest.json"

TRANSCRIPTS_ROOT.mkdir(exist_ok=True)
DIGEST_DIR.mkdir(exist_ok=True)

# ----------------- config -----------------
WAIT_BEFORE_DOWNLOAD_SECONDS = int(os.getenv("WAIT_BEFORE_DOWNLOAD_SECONDS", "15"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "5"))

try:
    HOBART_NOW = datetime.now(ZoneInfo("Australia/Hobart"))
    DEFAULT_YEAR = HOBART_NOW.year
except Exception:
    DEFAULT_YEAR = datetime.now().year

YEAR = int(os.getenv("YEAR", str(DEFAULT_YEAR)))

# Use the House-of-Assembly advanced page and override the hidden author field for each House.
ADV_SEARCH_URL = "https://search.parliament.tas.gov.au/adv/hahansard"

HOUSES = [
    {"label": "House of Assembly", "slug": "House_of_Assembly"},
    {"label": "Legislative Council", "slug": "Legislative_Council"},
]

# ----------------- helpers -----------------
def house_dir(slug: str) -> Path:
    d = TRANSCRIPTS_ROOT / slug
    d.mkdir(parents=True, exist_ok=True)
    return d

def sanitize_filename(title: str) -> str:
    # Normalise oddities (e.g., Wednesday2 -> Wednesday 2)
    title = re.sub(r"([A-Za-z])(\d)", r"\1 \2", title)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")
    return f"{safe}.txt"

def load_keywords():
    if not KEYWORDS_FILE.exists():
        return []
    return [
        ln.strip()
        for ln in KEYWORDS_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]

def extract_quotes(text, keywords, context_chars=160):
    results = []
    for kw in keywords:
        for m in re.finditer(re.escape(kw), text, flags=re.I):
            start = max(0, m.start() - context_chars)
            end = min(len(text), m.end() + context_chars)
            snippet = text[start:end].replace("\r", "").strip()
            results.append((kw, snippet))
    return results

def make_combined_digest(new_by_house, keywords):
    """
    new_by_house: dict[label] = [paths]
    Returns digest path or None.
    """
    # Only build if there is at least one new file across both Houses
    if not any(new_by_house.values()):
        return None

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%MZ")
    digest_path = DIGEST_DIR / f"Hansard_Keyword_Digest_{now}.txt"

    lines = []
    lines.append(f"Hansard Keyword Digest — generated {now}")
    if keywords:
        lines.append(f"Keywords: {', '.join(keywords)}")
    else:
        lines.append("(No keywords provided — showing file list only)")
    lines.append("")

    for house_label, files in new_by_house.items():
        if not files:
            continue
        lines.append(f"=== {house_label} ===")
        for fp in files:
            p = Path(fp)
            lines.append(f"\n--- {p.name} ---")
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                lines.append(f"  (could not read file: {e})")
                continue
            if not keywords:
                # No keywords — just note the file
                lines.append("  (no keywords configured)")
                continue
            hits = extract_quotes(text, keywords)
            if not hits:
                lines.append("  (no matches)")
                continue
            for i, (kw, quote) in enumerate(hits, 1):
                lines.append(f"[{i}] match: {kw}")
                for para in textwrap.wrap(quote, width=100):
                    lines.append(f"  {para}")
            lines.append("")  # spacer between files
        lines.append("")      # spacer between houses

    digest_path.write_text("\n".join(lines), encoding="utf-8")
    return str(digest_path)

def expose_outputs(new_count, digest_path):
    gh_out = os.getenv("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            print(f"new_downloads={new_count}", file=f)
            if digest_path:
                print(f"digest_path={digest_path}", file=f)

def save_manifest(new_by_house, new_count, digest_path):
    MANIFEST_FILE.write_text(
        json.dumps(
            {"new_by_house": new_by_house, "new_count": new_count, "digest_path": digest_path},
            indent=2,
        ),
        encoding="utf-8",
    )

# ----------------- page actions -----------------
def open_advanced_search(page):
    page.goto(ADV_SEARCH_URL, wait_until="domcontentloaded")
    # Ensure at least one year checkbox is present
    page.wait_for_selector('input[name="IW_FILTER_PATH"]', timeout=20000)

def set_year_checkboxes(page, year: int):
    # Toggle checkboxes so ONLY the current year is selected (best effort)
    all_checks = page.locator('input[name="IW_FILTER_PATH"]')
    count = all_checks.count()
    for i in range(count):
        el = all_checks.nth(i)
        try:
            v = el.get_attribute("value") or ""
            if str(year) in v:
                el.check()
            else:
                try:
                    el.uncheck()
                except Exception:
                    pass
        except Exception:
            pass

def set_house_filter(page, house_label: str):
    # Override the hidden author filter to the desired House
    page.evaluate(
        """(label) => {
            const input = document.querySelector('input[name="IW_FIELD_IN_AUTHOR"]');
            if (input) input.value = label;
        }""",
        house_label,
    )

def submit_search(page):
    # Click the visible Search button
    page.click('#isys_btn_search')
    page.wait_for_selector("table.results-table", timeout=20000)

def iter_results_on_page(page):
    links = page.locator('table.results-table a[href*="/doc/"]')
    n = links.count()
    items = []
    for i in range(n):
        a = links.nth(i)
        try:
            title = (a.inner_text(timeout=5000) or "").strip()
        except PWTimeout:
            title = "Untitled"
        items.append((title, a))
    return items

def go_next_page(page):
    try:
        next_link = page.locator("#isys_var_nextbatch")
        if next_link.count() == 0:
            return False
        if "disabled" in (next_link.get_attribute("disabled") or ""):
            return False
        next_link.click()
        page.wait_for_selector("table.results-table", timeout=15000)
        return True
    except Exception:
        return False

def download_current_document_txt(page, outfile: Path) -> bool:
    page.wait_for_selector("#viewer_toolbar", timeout=20000)
    # Allow viewer to fully render (PDF → HTML → toolbar wiring)
    time.sleep(WAIT_BEFORE_DOWNLOAD_SECONDS)

    page.wait_for_selector("div.btn.btn-download", timeout=15000)
    page.click("div.btn.btn-download")

    page.wait_for_selector("#viewer_toolbar_download", timeout=15000)
    with page.expect_download(timeout=60000) as d_info:
        page.click('#viewer_toolbar_download li:has-text("As Text")')
    d = d_info.value
    d.save_as(str(outfile))
    return True

def close_viewer(page):
    try:
        page.click("div.btn.btn-close", timeout=5000)
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

# ----------------- main -----------------
def main():
    new_by_house = {h["label"]: [] for h in HOUSES}
    total_new = 0

    print(f"Year = {YEAR}")
    print(f"Max pages per House = {MAX_PAGES}")
    print(f"Transcripts root = {TRANSCRIPTS_ROOT}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        for house in HOUSES:
            label = house["label"]
            slug = house["slug"]
            outdir = house_dir(slug)

            print(f"\n=== {label} ===")
            print(f"Opening Advanced Search… ({ADV_SEARCH_URL})")
            open_advanced_search(page)
            set_year_checkboxes(page, YEAR)
            set_house_filter(page, label)
            submit_search(page)

            for page_idx in range(1, MAX_PAGES + 1):
                print(f"Scanning results page {page_idx}…")
                items = iter_results_on_page(page)
                if not items:
                    print("No results on this page.")
                    break

                for title, link in items:
                    # Guard: ensure title references this House (usually does)
                    if label not in title:
                        # Be conservative: skip cross-house noise
                        continue

                    outfile = outdir / sanitize_filename(title)
                    if outfile.exists():
                        continue

                    print(f"→ Opening: {title}")
                    try:
                        link.click()
                        ok = download_current_document_txt(page, outfile)
                        if ok:
                            print(f"   ✅ Saved: {outfile.name}")
                            new_by_house[label].append(str(outfile))
                            total_new += 1
                        else:
                            print("   ⚠️  Download did not complete.")
                    except PWTimeout:
                        print("   ⚠️  Timed out opening/downloading; skipping.")
                    except Exception as e:
                        print(f"   ⚠️  Error: {e}")
                    finally:
                        close_viewer(page)

                if page_idx >= MAX_PAGES:
                    break
                if not go_next_page(page):
                    break

        context.close()
        browser.close()

    # Build combined digest (one file, with sections per House)
    keywords = load_keywords()
    digest_path = make_combined_digest(new_by_house, keywords)

    # Persist manifest & expose outputs
    save_manifest(new_by_house, total_new, digest_path)
    expose_outputs(total_new, digest_path)

    print(f"\nDone. New downloads this run: {total_new}")
    if digest_path:
        print(f"Digest: {digest_path}")

if __name__ == "__main__":
    main()
