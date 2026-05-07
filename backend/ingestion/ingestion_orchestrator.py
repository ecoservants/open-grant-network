import yaml
from backend.services.connectors import run_irs_ingestion, run_bmf_ingestion
from backend.services.connectors import run_grants_ingestion
import logging
import os
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)

# Load configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Build full path to config.yaml
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yaml")

# Load YAML
with open(CONFIG_PATH) as f:
    run_modes = yaml.safe_load(f)

def run_pipeline(mode, debug_limit: int = None):
    config = run_modes.get(mode)
    if not config:
        raise ValueError(f"Run mode {mode} not found in config")

    summaries = []

    for dataset in config["datasets"]:
        logging.info(f"Processing dataset: {dataset}")

        try:
            if dataset == "irs_990":
                summary = run_irs_ingestion(mode, debug_limit)
            elif dataset == "bmf":
                summary = run_bmf_ingestion(mode, debug_limit)
            elif dataset == "grants_gov":
                summary = run_grants_ingestion(mode, debug_limit)
            else:
                logging.warning(f"No connector for dataset: {dataset}")
                continue

            summaries.append(summary)

        except Exception as e:
            logging.error(f"Error processing {dataset}: {e}")
            if config.get("stop_on_error"):
                raise

    # summary report
    report_file = Path("../reports") / f"summary_{mode}.txt"
    report_file.parent.mkdir(exist_ok=True)

    with open(report_file, "w") as f:
        for summary in summaries:
            f.write(f"{summary}\n")

    logging.info(f"Summary report written to {report_file}")



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="full_ingest", help="Run mode: full_ingest, incremental, debug")
    args = parser.parse_args()
    
    run_pipeline(args.mode, debug_limit=None)