import os
import logging
import json
from jsonschema import validate, ValidationError

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
SCHEMA_PATH = os.path.join(ROOT_DIR, "docs", "schema", "grants_gov_schema.json")

with open(SCHEMA_PATH) as f:
    GRANT_SCHEMA = json.load(f)

# validation and error logging.
def validate_grant(grant, folder="../../../logs"):
    """
    Validate a single normalized grant record and log any missing required fields.

    Args:
        grant (dict): A normalized grant record following the OGN standard schema.
        folder (str, optional): Path to the folder where the log file will be saved.
            Defaults to "../../../logs".

    Returns:
        bool: True if all required fields are present, False if any required field is missing.

    Notes:
        - Required fields include:
            id, number, title, agency_code, agency, open_date,
            opportunity_status, document_type, cfda_list
        - optional: close_date
        - Creates the log directory if it does not exist.
        - Logs warnings to 'grants_ingest.log' for any missing fields.
        - Does not raise exceptions; simply returns False if validation fails.
    """
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, "grants_ingest.log")

    logging.basicConfig(
        filename=file_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    # -------------------------
    # Schema validation
    # -------------------------
    try:
        validate(instance=grant, schema=GRANT_SCHEMA)
    except ValidationError as e:
        logging.error(
            f"Schema validation failed for grant {grant.get('id')}: {e.message}"
        )
        return False

    # -------------------------
    # Business validation
    # -------------------------
    required_fields = [
        "id", "number", "title", "agency_code", "agency",
        "open_date", "opportunity_status",
        "document_type", "cfda_list"
    ]

    missing = [f for f in required_fields if not grant.get(f)]

    if missing:
        logging.warning(
            f"Missing required fields {missing} in grant {grant.get('id')}"
        )
        return False

    return True