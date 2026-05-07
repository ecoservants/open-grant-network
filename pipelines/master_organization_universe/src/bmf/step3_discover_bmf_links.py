import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

INDEX_URL = os.getenv(
    "BMF_INDEX_URL",
    "https://www.irs.gov/charities-non-profits/exempt-organizations-business-master-file-extract-eo-bmf",
)
DOWNLOAD_DIR = os.getenv("BMF_DOWNLOAD_DIR", "data/raw/bmf")


@dataclass
class BmfDiscoveryResult:
    posting_date: str | None  # YYYY-MM-DD if detected
    csv_links: list[str]


def _extract_posting_date(text: str) -> str | None:
    """
    Detect posting date in:
      - Month DD, YYYY (e.g., January 5, 2026)
      - MM/DD/YYYY
      - YYYY-MM-DD
    Return ISO date YYYY-MM-DD if found.
    """
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", text)
    if m:
        month_str, day, year = m.group(1), int(m.group(2)), int(m.group(3))
        months = {
            "January": 1, "February": 2, "March": 3, "April": 4,
            "May": 5, "June": 6, "July": 7, "August": 8,
            "September": 9, "October": 10, "November": 11, "December": 12
        }
        if month_str in months:
            return f"{year:04d}-{months[month_str]:02d}-{day:02d}"

    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        mm, dd, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{yyyy:04d}-{mm:02d}-{dd:02d}"

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return m.group(0)

    return None


def discover_bmf_links(index_url: str) -> BmfDiscoveryResult:
    r = requests.get(index_url, timeout=60)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    full_text = soup.get_text(" ", strip=True)

    posting_date = _extract_posting_date(full_text)

    links = []
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue

        # BeautifulSoup typing sometimes treats href as list-like, handle safely
        if isinstance(href, list):
            href = href[0]

        href = str(href).strip()
        abs_url = urljoin(index_url, href)

        if abs_url.lower().endswith(".csv"):
            links.append(abs_url)

    # Deduplicate preserving order
    seen = set()
    csv_links = []
    for u in links:
        if u not in seen:
            seen.add(u)
            csv_links.append(u)

    return BmfDiscoveryResult(posting_date=posting_date, csv_links=csv_links)


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    result = discover_bmf_links(INDEX_URL)

    print("IRS EO BMF index URL:", INDEX_URL)
    print("Detected posting date:", result.posting_date)
    print("CSV links found:", len(result.csv_links))

    out_path = os.path.join(DOWNLOAD_DIR, "bmf_discovery.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"index_url={INDEX_URL}\n")
        f.write(f"posting_date={result.posting_date}\n")
        f.write(f"csv_link_count={len(result.csv_links)}\n")
        for u in result.csv_links:
            f.write(u + "\n")

    print("Saved discovery output to:", out_path)

    # Show first 10 links for quick check
    for u in result.csv_links[:10]:
        print(" -", u)


if __name__ == "__main__":
    main()