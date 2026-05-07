import pandas as pd
import requests, zipfile, io, os
from backend.utils.logger import setup_file_logger
from backend.services.connectors.irs import validate_irs_row_with_schema, normalize_irs_990
import re 

logger = setup_file_logger("ingest_logs", "irs_990_errors.log")

YEARS = list(range(2012, 2025))  # 2012-2024

def download_and_extract_990(year: int) -> pd.DataFrame:
    """Download IRS 990 CSV or DAT ZIP for the given year and extract EINs only."""
    
    urls = [
        f"https://www.irs.gov/pub/irs-soi/{str(year)[-2:]}eoextract990.zip",   # CSV
        f"https://www.irs.gov/pub/irs-soi/{str(year)[-2:]}eofinextract990.zip" # DAT
    ]
    
    for url in urls:
        try:
            r = requests.get(url, timeout=30)
            # This ensures 404 or 500 triggers an exception
            r.raise_for_status()  
            z = zipfile.ZipFile(io.BytesIO(r.content))
            print(f"{year}: Found files in ZIP -> {z.namelist()}")

            # zip can have dat or CSV file
            csv_files = [f for f in z.namelist() if f.endswith(".csv")]
            dat_files = [f for f in z.namelist() if f.endswith(".dat")]

            if csv_files:
                file_name = csv_files[0]
                df = pd.read_csv(z.open(file_name), dtype=str)
            elif dat_files:
                file_name = dat_files[0]
                try:
                    df = pd.read_fwf(z.open(file_name), colspecs=[(0,9)], names=['EIN'], dtype=str)
                    df['EIN'] = df['EIN'].str.strip()
                except Exception:
                    df = pd.read_csv(z.open(file_name), sep=r"\s+", header=None, names=['EIN'], dtype=str)
                    df['EIN'] = df['EIN'].str.strip()
            else:
                raise ValueError("No CSV or DAT file found in ZIP")
            
            # normalize column names
            df = normalize_irs_990(df, year, logger)

            # Validate EINs (must be 9 digits)
            valid_mask = df['EIN'].apply(validate_irs_row_with_schema)
            df = df[valid_mask]

            return df.reset_index(drop=True)

        except requests.HTTPError as e:
            logger.warning(f"{year}: HTTP error {e} at {url}, trying next URL...")
            continue  # try next URL
        except Exception as e:
            logger.warning(f"{year}: Failed to download/extract from {url}: {e}, trying next URL...")
            continue  # try next URL

    # If all URLs fail
    logger.error(f"All attempts failed for IRS 990 {year}")
    return pd.DataFrame(columns=['EIN'])

def get_last_ingested_year_from_files(dataset_folder, prefix="irs_990_"):
    if not os.path.exists(dataset_folder):
        return None  # no files yet
    
    years = []
    for fname in os.listdir(dataset_folder):
        if fname.startswith(prefix) and fname.endswith(".csv"):
            match = re.search(r'(\d{4})', fname)
            if match:
                years.append(int(match.group(1)))
    
    if years:
        return max(years)
    return None

def run_irs_ingestion(mode, debug_limit: int = None) -> dict:
    """Ingest IRS 990 files for all years, save EIN-only CSV files, and return summary."""
    
    summary = {
        "source": "irs_990",
        "fetched": 0,
        "validated": 0,
        "failed": 0
    }

    output_dir = os.path.join("datasets", "irs_990", "normalized")
    os.makedirs(output_dir, exist_ok=True)

    if(mode == "incremental"):
        last_year = get_last_ingested_year_from_files(output_dir)
        print("Last ingested year:", last_year)
        years_to_ingest = list(range(last_year + 1, 2025))  # or CURRENT_YEAR
    elif(mode == "full_ingest"):
        years_to_ingest = YEARS
    elif(mode == "debug"):
        years_to_ingest = [2023]  # specific year for testing

    for year in years_to_ingest:
        df_990 = download_and_extract_990(year)
        if debug_limit is not None:
            df_990 = df_990.head(debug_limit) # for debug mode

        fetched_count = df_990.shape[0]
        summary["fetched"] += fetched_count

        if fetched_count > 0:
            # Validate EINs (must be 9 digits)
            valid_mask = df_990['EIN'].apply(validate_irs_row_with_schema)
            valid_count = valid_mask.sum()
            failed_count = fetched_count - valid_count

            summary["validated"] += valid_count
            summary["failed"] += failed_count

            df_990 = df_990[valid_mask]

        output_file = os.path.join(output_dir, f"irs_990_{year}.csv")
        try:
            if df_990.shape[0] > 0:
                df_990.to_csv(output_file, index=False)
            logger.info(f"IRS 990 {year} saved: {df_990.shape[0]} valid EINs (overwrite if exists)")
            print(f"Year {year} processed, saved {df_990.shape[0]} EINs.")
        except Exception as e:
            summary["failed"] += 1
            logger.error(f"Failed to save IRS 990 csv for {year}: {e}")
            print(f"Failed to save IRS 990 csv for {year}: {e}")

    logger.info(f"IRS 990 ingestion summary: {summary}")
    return summary

if __name__ == "__main__":
    run_irs_ingestion("full_ingest")
    print("IRS 990 ingestion complete for all years.")
