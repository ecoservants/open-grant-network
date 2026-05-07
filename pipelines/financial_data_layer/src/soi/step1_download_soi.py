import os
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

SOI_INDEX_URL = os.getenv(
    "SOI_INDEX_URL",
    "https://www.irs.gov/statistics/soi-tax-stats-annual-extract-of-tax-exempt-organization-financial-data",
)
SOI_DOWNLOAD_DIR = os.getenv("SOI_DOWNLOAD_DIR", "data/raw/soi")
SOI_TAX_YEARS    = os.getenv("SOI_TAX_YEARS", "2021,2022,2023").strip()  # comma-separated


def _extract_year_from_url(url: str) -> str | None:
    """
    IRS SOI filenames look like:
      15eofinextract990.zip  (tax year 2015)
      22eofinextract990.zip  (tax year 2022)
    Extract the 2-digit prefix and convert to 4-digit year.
    """
    name = os.path.basename(urlparse(url).path).lower()
    m = re.match(r"^(\d{2})", name)
    if m:
        yy = int(m.group(1))
        # IRS files: 96-99 = 1990s, 00-99 = 2000s
        yyyy = 1900 + yy if yy >= 96 else 2000 + yy
        return str(yyyy)
    return None


def _extract_year_from_text(text: str, url: str) -> str | None:
    """Fallback: look for a 4-digit year near the link text."""
    m = re.search(r"(20\d{2}|19\d{2})", text)
    if m:
        return m.group(1)
    return _extract_year_from_url(url)


def discover_soi_links(index_url: str) -> dict[str, str]:
    """
    Returns dict of {tax_year_str: download_url} for all
    .zip or .csv SOI extract files found on the IRS page.
    """
    print("Fetching SOI index:", index_url)
    r = requests.get(index_url, timeout=60)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    results = {}

    for a in soup.find_all("a"):
        href = a.get("href", "")
        if isinstance(href, list):
            href = href[0]
        href = str(href).strip()

        # Only .zip or .csv extract files
        if not (href.lower().endswith(".zip") or href.lower().endswith(".csv")):
            continue
        if "eofinextract" not in href.lower() and "soi" not in href.lower():
            continue

        abs_url = urljoin(index_url, href)
        link_text = a.get_text(" ", strip=True)
        year = _extract_year_from_text(link_text, abs_url)

        if year:
            # Keep the most recent URL if duplicates exist for same year
            if year not in results:
                results[year] = abs_url
                print(f"  Found: year={year}  url={abs_url}")

    return results


def download_file(url: str, out_path: str, timeout: int = 300, retries: int = 3) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        print("SKIP (exists):", out_path)
        return

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            print(f"Downloading (attempt {attempt}): {url}")
            with requests.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                tmp = out_path + ".part"
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                os.replace(tmp, out_path)
            print("OK:", out_path)
            return
        except Exception as e:
            last_err = e
            print(f"  Retry error: {e}")
            time.sleep(2 * attempt)

    raise RuntimeError(
        f"Failed after {retries} attempts: {url}\nLast error: {last_err}"
    )


def main():
    os.makedirs(SOI_DOWNLOAD_DIR, exist_ok=True)

    target_years = set(y.strip() for y in SOI_TAX_YEARS.split(",") if y.strip())
    print("Target years:", target_years)

    available = discover_soi_links(SOI_INDEX_URL)
    print(f"\nFound {len(available)} SOI extract links on IRS page.")

    if not available:
        raise RuntimeError(
            "No SOI extract links found. The IRS page structure may have changed.\n"
            "Check manually: " + SOI_INDEX_URL
        )

    # Save discovery manifest
    manifest_path = os.path.join(SOI_DOWNLOAD_DIR, "soi_discovery.txt")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(f"index_url={SOI_INDEX_URL}\n")
        for yr, url in sorted(available.items()):
            f.write(f"{yr}={url}\n")
    print("Manifest saved:", manifest_path)

    # Download selected years
    downloaded = []
    for year in sorted(target_years):
        if year not in available:
            print(f"WARNING: year {year} not found on IRS page — skipping.")
            continue

        url = available[year]
        ext = os.path.splitext(urlparse(url).path)[1].lower()
        filename = f"soi_{year}{ext}"
        out_path = os.path.join(SOI_DOWNLOAD_DIR, filename)
        download_file(url, out_path)
        downloaded.append((year, out_path))

    print(f"\nDownloaded {len(downloaded)} file(s):")
    for yr, path in downloaded:
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"  {yr}  {path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
