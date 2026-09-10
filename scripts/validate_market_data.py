#!/usr/bin/env python3
"""Validate publishable market-data and history files.

The checks are intentionally trust-focused:

- unverified instruments must not carry publishable numeric levels
- verified instruments need numeric levels and concrete source provenance
- history points must be verified, numeric, dated, de-duplicated, and ordered
- source URLs must be absolute http(s) URLs
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from provider_mappings import ALPHA_VANTAGE_SERIES, ALL_SOURCE_MAPPINGS, FRED_SERIES
from update_market_data import is_absolute_http_url, is_missing, parse_float


PUBLISHABLE_FIELDS = ("latest", "change1d", "change1w")
PROVENANCE_FIELDS = ("timestamp", "sourceName", "sourceUrl")
FRESHNESS_FREQUENCIES = {"intraday", "daily", "weekly", "monthly"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def is_numeric(value: Any) -> bool:
    parsed = parse_float(value)
    return parsed is not None and math.isfinite(parsed)


def normalize_frequency(value: Any) -> str | None:
    if is_missing(value):
        return None
    normalized = str(value).strip().lower()
    for frequency in FRESHNESS_FREQUENCIES:
        if frequency in normalized:
            return frequency
    return None


def validate_unique_ids(items: list[dict[str, Any]], label: str, errors: list[str]) -> None:
    seen: set[str] = set()
    for item in items:
        item_id = item.get("id")
        if not item_id:
            errors.append(f"{label} contains an entry without an id")
            continue
        if item_id in seen:
            errors.append(f"{label} contains duplicate id {item_id}")
        seen.add(item_id)


def validate_instruments(data: dict[str, Any], errors: list[str]) -> None:
    instruments = data.get("instruments", [])
    if not isinstance(instruments, list):
        errors.append("market-data instruments must be a list")
        return

    validate_unique_ids(instruments, "market-data instruments", errors)

    for instrument in instruments:
        instrument_id = instrument.get("id", "<missing>")
        verified = instrument.get("verified") is True

        if verified:
            if not is_numeric(instrument.get("latest")):
                errors.append(f"{instrument_id}: verified latest must be numeric and non-placeholder")
            for field_name in PROVENANCE_FIELDS:
                if is_missing(instrument.get(field_name)):
                    errors.append(f"{instrument_id}: verified {field_name} is required")
            if not is_absolute_http_url(instrument.get("sourceUrl")):
                errors.append(f"{instrument_id}: verified sourceUrl must be absolute http(s)")
            if normalize_frequency(instrument.get("frequency")) is None:
                errors.append(f"{instrument_id}: verified frequency is required for freshness classification")
            for field_name in ("change1d", "change1w"):
                if not is_missing(instrument.get(field_name)) and not is_numeric(instrument.get(field_name)):
                    errors.append(f"{instrument_id}: {field_name} must be numeric when present")
            continue

        for field_name in PUBLISHABLE_FIELDS:
            if not is_missing(instrument.get(field_name)):
                errors.append(f"{instrument_id}: unverified {field_name} must remain placeholder/missing")


def validate_history(history: dict[str, Any], errors: list[str]) -> None:
    series_list = history.get("series", [])
    if not isinstance(series_list, list):
        errors.append("history series must be a list")
        return

    validate_unique_ids(series_list, "history series", errors)
    series_ids = {series.get("id") for series in series_list}

    for mapping in ALL_SOURCE_MAPPINGS.values():
        if mapping.history_series_id and mapping.history_series_id not in series_ids:
            errors.append(f"{mapping.instrument_id}: missing history series {mapping.history_series_id}")
        if mapping.enabled and not is_absolute_http_url(mapping.source_url):
            errors.append(f"{mapping.instrument_id}: mapping source_url must be absolute http(s)")
        if mapping.enabled and mapping.redistribution_review_required:
            errors.append(f"{mapping.instrument_id}: redistribution-review mapping must not be enabled by default")

    if "gold" in FRED_SERIES or any(mapping.provider_symbol == "GOLDAMGBD228NLBM" for mapping in FRED_SERIES.values()):
        errors.append("obsolete FRED gold mapping GOLDAMGBD228NLBM must not be live-enabled")

    premium_index_ids = [
        mapping.instrument_id
        for mapping in ALPHA_VANTAGE_SERIES.values()
        if mapping.enabled and mapping.function == "INDEX_DATA"
    ]
    if premium_index_ids:
        errors.append(f"Alpha Vantage premium INDEX_DATA mappings must not be enabled by default: {', '.join(premium_index_ids)}")

    for series in series_list:
        series_id = series.get("id", "<missing>")
        points = series.get("points", [])
        if not isinstance(points, list):
            errors.append(f"{series_id}: points must be a list")
            continue

        dates = [point.get("date") for point in points if isinstance(point, dict)]
        if dates != sorted(dates):
            errors.append(f"{series_id}: history points must be chronologically sorted")
        if len(dates) != len(set(dates)):
            errors.append(f"{series_id}: history points must not contain duplicate dates")

        for point in points:
            if not isinstance(point, dict):
                errors.append(f"{series_id}: each history point must be an object")
                continue
            point_date = point.get("date")
            if not is_iso_date(point_date):
                errors.append(f"{series_id}: history point has invalid date {point_date!r}")
            if not is_numeric(point.get("value")):
                errors.append(f"{series_id}: history value for {point_date} must be numeric and non-placeholder")
            if point.get("verified") is not True:
                errors.append(f"{series_id}: history point for {point_date} must be verified")
            for field_name in PROVENANCE_FIELDS:
                if is_missing(point.get(field_name)):
                    errors.append(f"{series_id}: history point {point_date} missing {field_name}")
            if not is_absolute_http_url(point.get("sourceUrl")):
                errors.append(f"{series_id}: history point {point_date} sourceUrl must be absolute http(s)")


def validate_files(data_file: Path, history_file: Path) -> list[str]:
    errors: list[str] = []
    validate_instruments(load_json(data_file), errors)
    validate_history(load_json(history_file), errors)
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate market-data JSON integrity.")
    parser.add_argument("--data-file", default="data/market-data.json")
    parser.add_argument("--history-file", default="data/history.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = validate_files(Path(args.data_file), Path(args.history_file))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Market data integrity checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
