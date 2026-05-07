import pandas as pd
import requests, io, os
from backend.services.connectors.irs import validate_bmf_row_with_schema, normalize_bmf_row
from backend.utils.logger import setup_file_logger
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from email.utils import parsedate_to_datetime
from datetime import datetime
from datetime import timezone

logger = setup_file_logger("ingest_logs", "bmf_errors.log")

BMF_INDEX_URL = "https://www.irs.gov/charities-non-profits/exempt-organizations-business-master-file-extract-eo-bmf"

def discover_bmf_files(index_url: str):
    """
    Scrape IRS BMF index page to find all CSV file links.
    Returns list of tuples: (state_code, csv_url)
    """
    r = requests.get(index_url, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    
    csv_links = []
    for a in soup.find_all("a"):
        href = a.get("href")
        if href and href.lower().endswith(".csv"):
            abs_url = urljoin(index_url, href)
            # extract state from filename eo_<state>.csv
            filename = href.split("/")[-1]
            parts = filename.replace(".csv", "").split("_")
            state_code = parts[-1]  # last part
            csv_links.append((state_code.lower(), abs_url))
    return csv_links

def get_last_modified(url):
    try:
        r = requests.head(url, timeout=30)
        r.raise_for_status()
        print(f"last_date{parsedate_to_datetime(r.headers.get("Last-Modified"))}")
        return parsedate_to_datetime(r.headers.get("Last-Modified"))
    except Exception as e:
        logger.error(f"Could not get Last-Modified for {url}: {e}")
        return None


def get_local_file_time(filepath):
    if not os.path.exists(filepath):
        return None
    print(f"curr_date{datetime.fromtimestamp(os.path.getmtime(filepath), tz=timezone.utc)}")

    return datetime.fromtimestamp(os.path.getmtime(filepath), tz=timezone.utc)

def download_bmf_state(state: str, url: str) -> pd.DataFrame:
    """Download a single state's BMF CSV and return only required columns
    Parse EIN, organization names, addresses, NTEE codes"""
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.content.decode('utf-8')), dtype=str)

        # Keep only required columns
        # added safe check for missing columns to avoid failure of pipeline if cols missings
        expected_cols = ['EIN', 'NAME', 'STREET', 'CITY', 'STATE', 'ZIP', 'NTEE_CD']

        missing_cols = set(expected_cols) - set(df.columns)

        if missing_cols:
            logger.warning(f"Missing expected columns: {missing_cols}")

        df = df.reindex(columns=expected_cols)
        print(f"Downloading BMF for {state.upper()}...")
        return df
    except Exception as e:
        logger.error(f"Failed to download/load BMF for {state}: {e}")
        return pd.DataFrame(columns=['EIN','NAME', 'STREET', 'CITY', 'STATE', 'ZIP', 'NTEE_CD'])

def run_bmf_ingestion(mode, debug_limit: int = None):

    summary = {
        "source": "irs_bmf",
        "fetched": 0,
        "normalized": 0,
        "validated": 0,
        "failed": 0
    }

    bmf_files = discover_bmf_files(BMF_INDEX_URL)

    for state, url in bmf_files:

        output_dir = os.path.join("datasets", "bmf", "normalized")
        os.makedirs(output_dir, exist_ok=True)

        output_file = os.path.join(output_dir, f"bmf_{state}.csv")

        # ---------------- FULL INGEST ----------------
        if mode == "full_ingest":

            df_state = download_bmf_state(state, url)

        # ---------------- INCREMENTAL ----------------
        elif mode == "incremental":

            server_date = get_last_modified(url)
            local_date = get_local_file_time(output_file)

            if local_date and server_date and server_date <= local_date:
                logger.info(f"{state.upper()} already up-to-date. Skipping.")
                continue

            df_state = download_bmf_state(state, url)

        else:
            raise ValueError("Mode must be 'full_ingest' or 'incremental'")

        summary["fetched"] += len(df_state)

        logger.info(f"BMF {state.upper()} loaded: {df_state.shape[0]} rows")

        normalized_rows = []

        for _, row in df_state.iterrows():
            try:
                funder = normalize_bmf_row(row)

                validate_bmf_row_with_schema(funder)

                normalized_rows.append(funder.model_dump())

                summary["normalized"] += 1
                summary["validated"] += 1

            except Exception as e:
                summary["failed"] += 1
                logger.error(f"EIN={row.get('EIN')} | Error={str(e)}")

        if normalized_rows:

            df_norm = pd.DataFrame(normalized_rows)

            df_norm.to_csv(output_file, index=False)

            logger.info(f"Saved {state.upper()} csv")

    logger.info(f"BMF ingestion complete: {summary}")

    return summary


if __name__ == "__main__":
    df_bmf = run_bmf_ingestion("full_ingest")
