def normalize_grant(grant):
    """
    Normalize a single grant record from Grants.gov API to the OGN standard schema.

    Args:
        grant (dict): A raw grant record as returned by the Grants.gov API.

    Returns:
        dict: A normalized grant record with standardized field names, including:
            - id
            - number
            - title
            - agency_code
            - agency
            - open_date
            - close_date
            - opportunity_status
            - document_type
            - cfda_list

    Notes:
        - Maps raw API field names to OGN standard field names.
        - Missing fields will be set to None.
    """
    normalized = {
        "id": grant.get("id"),
        "number": grant.get("number"),
        "title": grant.get("title"),
        "agency_code": grant.get("agencyCode"),
        "agency": grant.get("agency"),
        "open_date": grant.get("openDate"),
        "close_date": grant.get("closeDate"),
        "opportunity_status": grant.get("oppStatus"),
        "document_type": grant.get("docType"),
        "cfda_list": grant.get("cfdaList"),
    }
    return normalized

def normalize_all(raw_data):
    """
    Normalize all grant records from the Grants.gov API response.

    Args:
        raw_data (dict): The raw API response containing multiple grant opportunities,
            typically under raw_data["data"]["oppHits"].

    Returns:
        list: A list of normalized grant records (dicts), where each record follows
            the OGN standard schema with fields like id, number, title, agency_code,
            agency, open_date, close_date, opportunity_status, document_type, and cfda_list.

    """
    return [normalize_grant(r) for r in raw_data]