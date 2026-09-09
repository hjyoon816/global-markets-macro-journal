#!/usr/bin/env python3
"""Placeholder-safe market data update pipeline.

This script is intentionally conservative. Provider adapters may fetch verified
market observations in future revisions, but this initial version never invents
or fabricates values. Missing credentials or provider failures leave existing
data untouched.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PLACEHOLDER = "—"
LOGGER = logging.getLogger("market-data")
REQUIRED_PROVENANCE_FIELDS = ("timestamp", "sourceName", "sourceUrl")
PUBLISHABLE_FIELDS = ("latest", "change1d", "change1w")
PROTECTED_VERIFIED_FIELDS = REQUIRED_PROVENANCE_FIELDS + PUBLISHABLE_FIELDS


@dataclass
class InstrumentUpdate:
    """A verified or explicitly sourced instrument update from a provider."""

    instrument_id: str
    fields: dict[str, Any]
    provider_name: str
    verified: bool = False
    reason: str = ""


@dataclass
class HistoryUpdate:
    """A verified history observation from a provider."""

    series_id: str
    date: str
    value: Any
    timestamp: str
    source_name: str
    source_url: str
    provider_name: str
    verified: bool = False
    reason: str = ""


@dataclass
class ProviderResult:
    provider_name: str
    status: str
    updates: list[InstrumentUpdate] = field(default_factory=list)
    history_updates: list[HistoryUpdate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ProviderAdapter:
    """Base class for market-data provider adapters."""

    name = "provider"
    required_env: tuple[str, ...] = ()

    def missing_env(self) -> list[str]:
        return [key for key in self.required_env if not os.environ.get(key)]

    def fetch_updates(self) -> ProviderResult:
        missing = self.missing_env()
        if missing:
            return ProviderResult(
                provider_name=self.name,
                status="skipped",
                errors=[f"Missing environment variables: {', '.join(missing)}"],
            )

        return self.fetch_verified_updates()

    def fetch_verified_updates(self) -> ProviderResult:
        return ProviderResult(
            provider_name=self.name,
            status="not_configured",
            errors=["Adapter stub is present, but no live provider mapping is configured."],
        )


class FredAdapter(ProviderAdapter):
    name = "FRED"
    required_env = ("FRED_API_KEY",)


class BokEcosAdapter(ProviderAdapter):
    name = "BOK ECOS"
    required_env = ("BOK_ECOS_API_KEY",)


class AlphaVantageAdapter(ProviderAdapter):
    name = "Alpha Vantage"
    required_env = ("ALPHA_VANTAGE_API_KEY",)


class CoinGeckoAdapter(ProviderAdapter):
    name = "CoinGecko"
    required_env = ("COINGECKO_API_KEY",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update verified market data JSON files.")
    parser.add_argument("--dry-run", action="store_true", help="Validate providers without writing files.")
    parser.add_argument("--data-file", default="data/market-data.json", help="Path to market data JSON.")
    parser.add_argument("--history-file", default="data/history.json", help="Path to history JSON.")
    parser.add_argument("--log-level", default="INFO", help="Python logging level.")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in {"", PLACEHOLDER}
    return False


def clean_value(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def is_absolute_http_url(value: Any) -> bool:
    if is_missing(value) or not isinstance(value, str):
        return False

    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False

    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def index_instruments(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {instrument["id"]: instrument for instrument in data.get("instruments", [])}


def has_required_provenance(update: InstrumentUpdate) -> bool:
    has_required_fields = all(
        not is_missing(update.fields.get(field_name))
        for field_name in REQUIRED_PROVENANCE_FIELDS
    )
    return has_required_fields and is_absolute_http_url(update.fields.get("sourceUrl"))


def has_publishable_value(update: InstrumentUpdate) -> bool:
    return any(not is_missing(update.fields.get(field_name)) for field_name in PUBLISHABLE_FIELDS)


def should_preserve_existing(existing: dict[str, Any], update: InstrumentUpdate, field_name: str) -> bool:
    if field_name not in PROTECTED_VERIFIED_FIELDS:
        return False

    incoming = update.fields.get(field_name)
    if not is_missing(incoming):
        return False

    return bool(existing.get("verified"))


def apply_updates(data: dict[str, Any], updates: list[InstrumentUpdate]) -> int:
    instruments = index_instruments(data)
    allowed_fields = {
        "latest",
        "change1d",
        "change1w",
        "timestamp",
        "sourceName",
        "sourceUrl",
        "verified",
        "status",
        "interpretation",
    }
    changed = 0

    for update in updates:
        if not update.verified:
            LOGGER.info(
                "Skipping unverified update for %s from %s: %s",
                update.instrument_id,
                update.provider_name,
                update.reason or "provider did not mark the observation verified",
            )
            continue

        if not has_required_provenance(update):
            LOGGER.warning(
                "Skipping verified update for %s from %s because timestamp, sourceName, and absolute http(s) sourceUrl are required",
                update.instrument_id,
                update.provider_name,
            )
            continue

        if not has_publishable_value(update):
            LOGGER.info(
                "Skipping verified update for %s from %s because it contains no publishable market value",
                update.instrument_id,
                update.provider_name,
            )
            continue

        instrument = instruments.get(update.instrument_id)
        if not instrument:
            LOGGER.warning("Ignoring update for unknown instrument id %s", update.instrument_id)
            continue

        for field_name, raw_incoming in update.fields.items():
            incoming = clean_value(raw_incoming)
            if field_name not in allowed_fields:
                LOGGER.warning("Ignoring unsupported field %s for %s", field_name, update.instrument_id)
                continue

            if field_name == "verified":
                continue

            if should_preserve_existing(instrument, update, field_name):
                LOGGER.info(
                    "Preserving verified %s for %s because provider returned no replacement value",
                    field_name,
                    update.instrument_id,
                )
                continue

            if is_missing(incoming):
                continue

            if instrument.get(field_name) != incoming:
                instrument[field_name] = incoming
                changed += 1

        if update.verified and not instrument.get("verified"):
            instrument["verified"] = True
            changed += 1

        if is_missing(update.fields.get("status")) and instrument.get("status") != "verified":
            instrument["status"] = "verified"
            changed += 1

    return changed


def history_update_has_provenance(update: HistoryUpdate) -> bool:
    return all(
        not is_missing(value)
        for value in (update.timestamp, update.source_name, update.source_url)
    ) and is_absolute_http_url(update.source_url)


def valid_history_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return True


def find_history_series(history: dict[str, Any], series_id: str) -> dict[str, Any] | None:
    for series in history.get("series", []):
        if series.get("id") == series_id:
            return series
    return None


def sorted_history_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(points, key=lambda point: point.get("date", ""))


def apply_history_updates(history: dict[str, Any], updates: list[HistoryUpdate]) -> int:
    """Apply verified history observations without fabricating missing values."""

    changed = 0

    for update in updates:
        if not update.verified:
            LOGGER.info(
                "Skipping unverified history update for %s from %s: %s",
                update.series_id,
                update.provider_name,
                update.reason or "provider did not mark the observation verified",
            )
            continue

        if not valid_history_date(update.date):
            LOGGER.warning("Skipping history update for %s because date is invalid", update.series_id)
            continue

        if is_missing(update.value):
            LOGGER.info("Skipping history update for %s because value is missing", update.series_id)
            continue

        if not history_update_has_provenance(update):
            LOGGER.warning(
                "Skipping history update for %s from %s because timestamp, sourceName, and absolute http(s) sourceUrl are required",
                update.series_id,
                update.provider_name,
            )
            continue

        series = find_history_series(history, update.series_id)
        if not series:
            LOGGER.warning("Ignoring history update for unknown series id %s", update.series_id)
            continue

        points = series.setdefault("points", [])
        replacement = {
            "date": clean_value(update.date),
            "value": update.value,
            "timestamp": clean_value(update.timestamp),
            "sourceName": clean_value(update.source_name),
            "sourceUrl": clean_value(update.source_url),
            "verified": True,
        }

        existing_index = next(
            (index for index, point in enumerate(points) if point.get("date") == update.date),
            None,
        )

        if existing_index is None:
            points.append(replacement)
            changed += 1
        elif points[existing_index] != replacement:
            points[existing_index] = replacement
            changed += 1

        ordered_points = sorted_history_points(points)
        if ordered_points != points:
            series["points"] = ordered_points
            changed += 1

    return changed


def provider_adapters() -> list[ProviderAdapter]:
    return [FredAdapter(), BokEcosAdapter(), AlphaVantageAdapter(), CoinGeckoAdapter()]


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    data_path = Path(args.data_file)
    history_path = Path(args.history_file)
    data = load_json(data_path)
    history = load_json(history_path)

    results: list[ProviderResult] = []
    updates: list[InstrumentUpdate] = []
    history_updates: list[HistoryUpdate] = []

    for adapter in provider_adapters():
        try:
            result = adapter.fetch_updates()
        except Exception as exc:  # noqa: BLE001 - adapters should never stop the whole pipeline.
            LOGGER.exception("Provider %s failed", adapter.name)
            result = ProviderResult(adapter.name, "failed", errors=[str(exc)])

        results.append(result)
        updates.extend(result.updates)
        history_updates.extend(result.history_updates)
        LOGGER.info(
            "%s status: %s, updates: %s, history updates: %s",
            result.provider_name,
            result.status,
            len(result.updates),
            len(result.history_updates),
        )
        for error in result.errors:
            LOGGER.info("%s detail: %s", result.provider_name, error)

    if args.dry_run:
        LOGGER.info("Dry run complete. No files were written.")
        return 0

    changed = apply_updates(data, updates)
    history_changed = apply_history_updates(history, history_updates)
    if changed == 0 and history_changed == 0:
        LOGGER.info("No verified data changes available. Existing files left untouched.")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    metadata = data.setdefault("metadata", {})
    metadata["asOf"] = now
    metadata["lastSuccessfulUpdate"] = now
    metadata["status"] = "updated"
    metadata["providerStatus"] = [
        {"name": result.provider_name, "status": result.status, "errors": result.errors}
        for result in results
    ]

    write_json(data_path, data)
    if history_changed:
        write_json(history_path, history)
    LOGGER.info(
        "Wrote verified updates: %s market field changes, %s history point changes.",
        changed,
        history_changed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
