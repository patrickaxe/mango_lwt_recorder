from __future__ import annotations

import csv
from io import StringIO


REQUIRED_TEMPLATE_COLUMNS = ("Block", "TreeID", "PanicleID")
OPTIONAL_TEMPLATE_COLUMNS = (
    "Cultivar",
    "L",
    "W",
    "T",
    "Weight",
    "Brix",
    "SamplingRole",
    "Comment",
)
TEMPLATE_COLUMNS = REQUIRED_TEMPLATE_COLUMNS + OPTIONAL_TEMPLATE_COLUMNS


def parse_template_csv(csv_text: str) -> list[dict[str, str]]:
    """Parse a worksheet template without treating its rows as measurements."""
    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff"), newline=""))
    if reader.fieldnames is None:
        raise ValueError("The template is empty or has no header row.")

    normalized_headers: dict[str, str] = {}
    for original_header in reader.fieldnames:
        header = (original_header or "").strip()
        if not header:
            continue
        key = header.casefold()
        if key in normalized_headers:
            raise ValueError(f'Duplicate template column: "{header}".')
        normalized_headers[key] = original_header

    missing_columns = [
        column
        for column in REQUIRED_TEMPLATE_COLUMNS
        if column.casefold() not in normalized_headers
    ]
    if missing_columns:
        raise ValueError(
            "Template is missing required column(s): "
            + ", ".join(missing_columns)
            + "."
        )

    rows: list[dict[str, str]] = []
    for csv_row_number, source_row in enumerate(reader, start=2):
        if None in source_row:
            raise ValueError(
                f"CSV row {csv_row_number} has more values than the header."
            )

        row = {}
        for column in TEMPLATE_COLUMNS:
            original_header = normalized_headers.get(column.casefold())
            value = source_row.get(original_header, "") if original_header else ""
            row[column] = (value or "").strip()
        if not any(row.values()):
            continue

        missing_values = [
            column for column in REQUIRED_TEMPLATE_COLUMNS if not row[column]
        ]
        if missing_values:
            raise ValueError(
                f"CSV row {csv_row_number} is missing required value(s): "
                + ", ".join(missing_values)
                + "."
            )
        rows.append(row)

    if not rows:
        raise ValueError("The template has no data rows.")
    return rows
