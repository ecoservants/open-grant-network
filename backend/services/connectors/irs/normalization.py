import pandas as pd
from pydantic import BaseModel, Field
from typing import Optional
import math

class Funder(BaseModel):
    ein: str = Field(..., pattern=r"^\d{9}$")
    name: Optional[str] = None 
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    ntee_code: Optional[str] = None


def normalize_irs_990(df: pd.DataFrame, year: int, logger) -> pd.DataFrame:
    """
    Normalize raw IRS 990 dataframe into canonical EIN-only format.
    """
    # Normalize column names
    df.columns = df.columns.str.upper()

    if 'EIN' not in df.columns:
        logger.error(f"EIN column missing for IRS 990 {year}")
        return pd.DataFrame(columns=['EIN'])

    # Keep only EIN column (canonical schema)
    df = df[['EIN']].copy()

    # Normalize EIN format
    df['EIN'] = (
        df['EIN']
        .astype(str)
        .str.strip()
    )

    return df.reset_index(drop=True)

def normalize_bmf_row(row: pd.Series) -> Funder:
    """
    Normalize a single BMF row into canonical Funder model.
    """

    def clean(val):
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        return str(val).strip()
    
    return Funder(
        ein=str(row.get('EIN', '')).zfill(9).strip(),
        name=clean(row.get('NAME')),
        street=clean(row.get('STREET')),
        city=clean(row.get('CITY')),
        state=clean(row.get('STATE')),
        zip=clean(row.get('ZIP')),
        ntee_code=clean(row.get('NTEE_CD'))
    )