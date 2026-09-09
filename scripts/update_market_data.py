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


PLACEHOLDER = "—"
LOGGER = logging.getLogger("market-data")


@dataclass
class InstrumentUpdate:
    """A verified or explicitly sourced instrument update from a provider."""

    instrument_id: str
    fields: dict[str, Any]
    provider_name: str
    verified: bool = False
    reason: str = ""


@dataclass
class ProviderResult:
    provider_name: str
    status: str
    updates: list[InstrumentUpdate] = field(default_factory=list)
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
    return value is None or value == "" or value == PLACEHOLDER


def index_instruments(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {instrument["id"]: instrument for instrument in data.get("instruments", [])}


def should_preserve_existing(existing: dict[str, Any], update: InstrumentUpdate, field_name: str) -> bool:
    if field_name not in {"latest", "change1d", "change1w"}:
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
        instrument = instruments.get(update.instrument_id)
        if not instrument:
            LOGGER.warning("Ignoring update for unknown instrument id %s", update.instrument_id)
            continue

        for field_name, incoming in update.fields.items():
            if field_name not in allowed_fields:
                LOGGER.warning("Ignoring unsupported field %s for %s", field_name, update.instrument_id)
                continue

            if should_preserve_existing(instrument, update, field_name):
                LOGGER.info(
                    "Preserving verified %s for %s because provider returned no replacement value",
                    field_name,
                    update.instrument_id,
                )
                continue

            if field_name in {"latest", "change1d", "change1w"} and is_missing(incoming):
                continue

            if instrument.get(field_name) != incoming:
                instrument[field_name] = incoming
                changed += 1

        if update.verified and not instrument.get("verified"):
            instrument["verified"] = True
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
    load_json(history_path)

    results: list[ProviderResult] = []
    updates: list[InstrumentUpdate] = []

    for adapter in provider_adapters():
        try:
            result = adapter.fetch_updates()
        except Exception as exc:  # noqa: BLE001 - adapters should never stop the whole pipeline.
            LOGGER.exception("Provider %s failed", adapter.name)
            result = ProviderResult(adapter.name, "failed", errors=[str(exc)])

        results.append(result)
        updates.extend(result.updates)
        LOGGER.info("%s status: %s, updates: %s", result.provider_name, result.status, len(result.updates))
        for error in result.errors:
            LOGGER.info("%s detail: %s", result.provider_name, error)

    if args.dry_run:
        LOGGER.info("Dry run complete. No files were written.")
        return 0

    changed = apply_updates(data, updates)
    if changed == 0:
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
    LOGGER.info("Wrote %s with %s field changes.", data_path, changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
