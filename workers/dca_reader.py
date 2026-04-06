import pandas as pd
import pickle
import os
from datetime import date
from core.models import DCAResult


# Define the data types for each column
tipos = {'License Number': 'int32', 'Org/Last Name': 'str', 'First Name': 'str', 'Middle Name': 'str', 'Suffix': 'str', 'License Type': 'str', 'License Status': 'str' }

# Read the Excel file with specified data types and columns
columns = ['License Number', 'Org/Last Name', 'First Name', 'Middle Name', 'Suffix', 'License Type', 'License Status', 'Original Issue Date', 'Expiration Date',]

if os.path.exists("./data/dca_data.pkl"):
    print("Loading from cache (Fast)...")
    with open("./data/dca_data.pkl", "rb") as f:
        full_data = pickle.load(f)
else:
    print("Reading Excel for the first time (Slow)...")
    full_data = pd.read_excel("./data/medical_board.xlsx", engine="openpyxl", dtype=tipos, usecols=columns)
    with open("./data/dca_data.pkl", "wb") as f:
        pickle.dump(full_data, f)


# ──────────────────────────────────────────────────────────────────
# Query functions
# ──────────────────────────────────────────────────────────────────

# These functions provide the public interface for querying DCA license data.
def query_by_license(license_number: str) -> DCAResult | None:
    """Find a license by its number and return a DCAResult instance."""

    row = full_data[full_data['License Number'] == int(license_number)]

    if row.empty:
        return None
    
    return _row_to_dca_result(row.iloc[0])


# Note: The name query is case-insensitive and matches both first and last names.
def query_by_name(last_name: str, first_name: str) -> list[DCAResult]:
    """Find licenses matching the given name and return a list of DCAResult."""
    
    matches = full_data[
        (full_data['Org/Last Name'].str.upper() == last_name.upper()) &
        (full_data['First Name'].str.upper() == first_name.upper())
    ]

    return [_row_to_dca_result(row) for _, row in matches.iterrows()]


# ──────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────

def _row_to_dca_result(row: pd.Series) -> DCAResult:
    """Convert a DataFrame row to a DCAResult model instance."""
    return DCAResult(
        license_number=str(row['License Number']),
        last_name=row['Org/Last Name'],
        first_name=row['First Name'],
        middle_name=row['Middle Name'] if pd.notna(row['Middle Name']) else None,
        license_type=row['License Type'],
        license_status=row['License Status'],
        expiration_date=row['Expiration Date'].date(),
        original_issue_date=row['Original Issue Date'].date(),
        is_valid=(row['License Status'] == 'Current') and (row['Expiration Date'].date() > date.today()),
    )
