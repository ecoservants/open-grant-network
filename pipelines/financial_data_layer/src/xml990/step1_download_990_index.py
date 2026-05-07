import os
import csv
import time

import requests
from dotenv import load_dotenv

load_dotenv()

XML990_DOWNLOAD_DIR = os.getenv("XML990_DOWNLOAD_DIR", "data/raw/xml990")
XML990_TAX_YEARS    = os.getenv("XML990_TAX_YEARS", "2021,2022,2023").strip()

# Correct IRS TEOS URL format (confirmed working as of 2025)
# Columns: RETURN_ID, FILING_TYPE, EIN, TAX_PERIOD, SUB_DATE,
#          TAXPAYER_NAME, RETURN_TYPE, DLN, OBJECT_ID
INDEX_URL_TEMPLATE = (
    "https://apps.irs.gov/pub/epostcard/990/xml/{year}/index_{year}.csv"
)


def download_index(year: int, out_dir: str, timeout: int = 300, retries: int = 3) -> str:
    os.makedirs(out_dir, exist_ok=True)
    url      = INDEX_URL_TEMPLATE.format(year=year)
    out_path = os.path.join(out_dir, f"index_{year}.csv")

    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        print(f"  SKIP (exists): {out_path}")
        return out_path

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            print(f"  Downloading (attempt {attempt}): {url}")
            with requests.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                tmp = out_path + ".part"
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                os.replace(tmp, out_path)
            size_mb = os.path.getsize(out_path) / (1024 * 1024)
            print(f"  OK: {out_path}  ({size_mb:.1f} MB)")
            return out_path
        except Exception as e:
            last_err = e
            print(f"  Error: {e}")
            time.sleep(2 * attempt)

    raise RuntimeError(
        f"Failed after {retries} attempts: {url}\nLast: {last_err}"
    )


def peek_index(csv_path: str) -> int:
    """Count rows and show sample from index CSV."""
    count   = 0
    sample  = None
    columns = None

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        for row in reader:
            count += 1
            if sample is None:
                sample = row

    print(f"  Total filings : {count:,}")
    print(f"  Columns       : {columns}")
    if sample:
        print(f"  Sample entry  : EIN={sample.get('EIN')} "
              f"FormType={sample.get('RETURN_TYPE')} "
              f"TaxPeriod={sample.get('TAX_PERIOD')} "
              f"ObjectId={sample.get('OBJECT_ID')}")
    return count


def main():
    target_years = sorted(
        int(y.strip()) for y in XML990_TAX_YEARS.split(",") if y.strip()
    )
    print(f"990 XML index downloader — years: {target_years}")
    print(f"Output dir: {XML990_DOWNLOAD_DIR}\n")

    for year in target_years:
        print(f"── Year {year} ──")
        path = download_index(year, XML990_DOWNLOAD_DIR)
        peek_index(path)
        print()

    print("Done. Index files ready for 990 XML parser.")


if __name__ == "__main__":
    main()
