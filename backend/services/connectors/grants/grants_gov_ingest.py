import requests
import os
import json
from backend.utils.file_utils import save_data
from backend.services.connectors.grants import normalize_all, validate_grant
import time

BASE_URL = "https://api.grants.gov/v1/api/search2"
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))

raw_op_folder = os.path.join(ROOT_DIR, "datasets", "grants_gov", "raw")
raw_op_file = "grants_raw.json"
normalized_op_folder = os.path.join(ROOT_DIR, "datasets", "grants_gov", "normalized")
normalized_op_file = "grants_normalized.json"
split_input_file = os.path.join(normalized_op_folder, normalized_op_file)
split_grants_op_folder = os.path.join(ROOT_DIR, "datasets", "grants_gov", "raw", "status_split")

def fetch_all_grants(rows_per_call=50, limit = None):
    """
    Fetch all grant listings from the Grants.gov API using pagination.

    Args:
        rows_per_call (int, optional): Number of grant records to fetch per API request. Defaults to 50.

    Returns:
        list: A list of all grant records returned by the API, where each record is a dictionary.

    Notes:
        - Uses POST requests to the Grants.gov search endpoint.
        - Handles pagination until all available grants are retrieved.
        - filtered - "oppStatuses": "active|forecasted|archived"
    """
    all_grants = []
    start = 0

    while True:
        payload = {
            "rows": rows_per_call,
            "startRecordNum": start,
            "oppStatuses": "active|forecasted|archived"
        }

        response = requests.post(BASE_URL, json=payload)
        # Basic rate-limit handling
        if response.status_code == 429:
            print("Rate limited. Sleeping 5 seconds...")
            time.sleep(5)
            continue

        response.raise_for_status()
        data = response.json()
        grants = data["data"]["oppHits"]

        if not grants:
            break

        all_grants.extend(grants)
        # stop early if limit reached
        if limit and len(all_grants) >= limit:
            return all_grants[:limit]
        start += len(grants)

        print(f"Fetched {len(all_grants)} grants so far...")

    return all_grants



# split grants by status
def split_grants_by_status(input_file, output_folder):
    """
    Split a single Grants.gov raw JSON file into multiple files by opportunity_status.

    Args:
        input_file (str): Path to the single raw JSON file.
        output_folder (str): Folder to save the split files.

    Returns:
        dict: Mapping of status -> saved file path
    """
    os.makedirs(output_folder, exist_ok=True)

    # Load raw data
    with open(input_file, "r") as f:
        all_grants = json.load(f)

    # Create dictionary to hold lists per status
    status_dict = {
        "active": [],
        "forecasted": [],
        "archived": []
    }

    # Distribute grants into status lists
    for grant in all_grants:
        status = grant.get("opportunity_status", "").lower()
        if status in status_dict:
            status_dict[status].append(grant)
        else:
            continue

    # Save each status list to separate file
    saved_files = {}
    for status, grants in status_dict.items():
        if not grants:
            continue 
        save_data(grants, output_folder, f"grants_{status}.json", f"Saved {len(grants)} '{status}' grants to ")
        file_path = os.path.join(output_folder, f"grants_{status}.json")
        saved_files[status] = file_path

    return saved_files

def run_grants_ingestion(mode, debug_limit: int = None) -> dict:

    """
    Run the full Grants.gov ingestion pipeline.

    Returns:
        dict: summary report
    """
    
    summary = {
        "source": "grants_gov",
        "fetched": 0,
        "normalized": 0,
        "validated": 0,
        "failed": 0
    }
    if(mode == "full_ingest"):
        raw_data = fetch_all_grants()
        summary["fetched"] = len(raw_data)

        save_data(raw_data, raw_op_folder, raw_op_file, "Saved raw data to")

        normalized = normalize_all(raw_data)
        summary["normalized"] = len(normalized)

        valid_records = []

        for opp in normalized:
            if validate_grant(opp):
                valid_records.append(opp)
                summary["validated"] += 1
            else:
                summary["failed"] += 1

        save_data(normalized, normalized_op_folder, normalized_op_file, "Saved normalized data to")

        split_grants_by_status(split_input_file, split_grants_op_folder)   
    elif(mode == "debug"):
        sample_records = fetch_all_grants(limit = debug_limit)
        sample_records_norm = normalize_all(sample_records) # records to test
        valid_count = sum(validate_grant(r) for r in sample_records_norm)
        print(f"{valid_count} out of {len(sample_records_norm)} records passed schema validation")

    else:
        raise ValueError("Mode must be 'full_ingest' or 'debug'")

    return summary

if __name__ == "__main__":
    run_grants_ingestion("full_ingest")
