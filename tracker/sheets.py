"""Google Sheets interface using gspread.

Column positions are detected dynamically from the header row so any column
ordering works. A blank leading column and a header not on row 1 are handled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_REQUIRED_COLUMNS = {"company", "role", "status"}
_OPTIONAL_COLUMNS = {"link", "location"}


def _open_worksheet(service_account_file: str, spreadsheet_id: str, worksheet_name: str):
    path = Path(service_account_file)
    if not path.exists():
        raise FileNotFoundError(
            f"Service account file not found: {path}\n"
            "See README.md § Google Service Account for setup instructions."
        )
    creds = Credentials.from_service_account_file(str(path), scopes=_SCOPES)
    gc = gspread.authorize(creds)
    try:
        sh = gc.open_by_key(spreadsheet_id)
    except gspread.exceptions.APIError as exc:
        raise RuntimeError(
            f"Could not open spreadsheet. Ensure the service account email has "
            f"Editor access to the sheet.\nDetails: {exc}"
        ) from exc
    return sh.worksheet(worksheet_name)


def _find_header(all_values: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Return (header_row_index, {column_name_lower: 0-based column index})."""
    for row_idx, row in enumerate(all_values):
        row_lower = [cell.lower().strip() for cell in row]
        if _REQUIRED_COLUMNS.issubset(set(row_lower)):
            col_map = {name: row_lower.index(name) for name in row_lower if name}
            return row_idx, col_map
    raise ValueError(
        "Could not find a header row containing 'Company', 'Role', and 'Status' "
        "(case-insensitive). Check the worksheet_name in config.toml and ensure "
        "those columns exist."
    )


def get_applications(
    service_account_file: str,
    spreadsheet_id: str,
    worksheet_name: str,
) -> list[dict[str, Any]]:
    """Return all application rows as a list of dicts with a 1-based row number."""
    ws = _open_worksheet(service_account_file, spreadsheet_id, worksheet_name)
    all_values = ws.get_all_values()

    header_row_idx, col_map = _find_header(all_values)

    applications = []
    for row_idx in range(header_row_idx + 1, len(all_values)):
        row = all_values[row_idx]
        if not any(cell.strip() for cell in row):
            continue

        def cell(col: str) -> str:
            idx = col_map.get(col)
            if idx is None or idx >= len(row):
                return ""
            return row[idx].strip()

        applications.append(
            {
                "row": row_idx + 1,  # gspread rows are 1-based
                "company": cell("company"),
                "role": cell("role"),
                "status": cell("status"),
                "link": cell("link"),
                "location": cell("location"),
            }
        )

    return applications


def update_status(
    service_account_file: str,
    spreadsheet_id: str,
    worksheet_name: str,
    row: int,
    new_status: str,
    dry_run: bool = True,
) -> None:
    """Write new_status to the Status cell of the given row."""
    ws = _open_worksheet(service_account_file, spreadsheet_id, worksheet_name)
    all_values = ws.get_all_values()
    _, col_map = _find_header(all_values)

    status_col = col_map.get("status")
    if status_col is None:
        raise RuntimeError("Status column not found — this should not happen after header detection.")

    # gspread uses 1-based col; col_map is 0-based
    col_letter = gspread.utils.rowcol_to_a1(row, status_col + 1)[:-len(str(row))]

    if dry_run:
        print(f"  [DRY RUN] Would write '{new_status}' to cell {col_letter}{row}")
        return

    ws.update_cell(row, status_col + 1, new_status)
