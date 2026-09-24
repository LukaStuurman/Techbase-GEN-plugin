"""Read the station-name lookup CSV used by the first workflow step."""

from __future__ import annotations

import csv
import io
from pathlib import Path


def _read_text(path):
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _unwrap_rows(text):
    """Unwrap the row-level quoting used by some GEN CSV exports."""
    lines = text.splitlines()
    if not lines:
        return text

    header = lines[0]
    wrapped = False
    if header.startswith('"') and header.endswith('"'):
        for delimiter in (",", ";", "\t"):
            try:
                outer_fields = next(csv.reader([header], delimiter=delimiter))
                inner = header[1:-1].replace('""', '"')
                inner_fields = next(csv.reader([inner], delimiter=delimiter))
            except (csv.Error, StopIteration):
                continue
            if len(outer_fields) == 1 and len(inner_fields) > 1:
                wrapped = True
                break

    if not wrapped:
        return text

    normalized = []
    for line in lines:
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1].replace('""', '"')
        normalized.append(line)
    return "\n".join(normalized)


def read_station_csv(path):
    """Return (headers, data_rows) from a comma, semicolon, or tab CSV."""
    text = _unwrap_rows(_read_text(path))
    sample = "\n".join(text.splitlines()[:10])
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","

    rows = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        headers = [str(value).strip() for value in next(rows)]
    except StopIteration:
        raise ValueError("Het CSV-bestand is leeg.")
    if not headers or not any(headers):
        raise ValueError("De CSV bevat geen kolomkoppen.")

    data = []
    for row_number, row in enumerate(rows, start=2):
        if not row or not any(str(value).strip() for value in row):
            continue
        if len(row) != len(headers):
            raise ValueError(
                f"CSV-regel {row_number} heeft {len(row)} waarden; "
                f"er worden {len(headers)} kolommen verwacht."
            )
        data.append(row)
    return headers, data


def _compact_name(value):
    return "".join(character.casefold() for character in str(value) if character.isalnum())


def find_master_asset_id_column(headers):
    wanted = {"masterassetid", "masterassetidentifier"}
    for header in headers:
        if _compact_name(header) in wanted:
            return header
    return None


def guess_station_name_column(headers):
    for header in headers:
        if _compact_name(header) == "sourcefile":
            return header
    wanted = {
        "station",
        "stationsnaam",
        "stationnaam",
        "stationname",
        "naamstation",
        "naamvanstation",
    }
    for header in headers:
        if _compact_name(header) in wanted:
            return header
    return None


def normalize_asset_id(value):
    text = str(value or "").strip()
    if text.casefold() in {"null", "none", "nan"}:
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.casefold()


def load_station_name_lookup(path, station_name_column):
    headers, rows = read_station_csv(path)
    key_column = find_master_asset_id_column(headers)
    if key_column is None:
        raise ValueError(
            "De CSV bevat geen kolom 'Master Asset ID' (of een herkenbare variant)."
        )

    selected = str(station_name_column or "").strip()
    name_column = next(
        (header for header in headers if header.casefold() == selected.casefold()),
        None,
    )
    if name_column is None:
        raise ValueError("Kies een bestaande stationsnaamkolom uit de CSV.")
    key_index = headers.index(key_column)
    name_index = headers.index(name_column)

    lookup = {}
    duplicate_count = 0
    skipped_count = 0
    for row_number, row in enumerate(rows, start=2):
        asset_id = normalize_asset_id(row[key_index])
        station_name = str(row[name_index] or "").strip()
        if not asset_id or not station_name or station_name.casefold() in {
            "null", "none", "nan"
        }:
            skipped_count += 1
            continue
        previous = lookup.get(asset_id)
        if previous is not None:
            if previous != station_name:
                raise ValueError(
                    f"Master Asset ID '{row[key_index]}' heeft meerdere "
                    f"stationsnamen (onder andere '{previous}' en '{station_name}'; "
                    f"CSV-regel {row_number})."
                )
            duplicate_count += 1
            continue
        lookup[asset_id] = station_name

    if not lookup:
        raise ValueError(
            f"Er zijn geen bruikbare waarden gevonden in kolom '{name_column}'."
        )
    return lookup, {
        "key_column": key_column,
        "name_column": name_column,
        "csv_rows": len(rows),
        "lookup_rows": len(lookup),
        "duplicate_rows": duplicate_count,
        "skipped_rows": skipped_count,
    }
