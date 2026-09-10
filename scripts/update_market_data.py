#!/usr/bin/env python3
"""Verified market data update pipeline.

The pipeline is deliberately conservative:

- provider credentials are read only from environment variables
- providers fail independently
- unverified or malformed observations are rejected before mutation
- history points are only appended/upserted from verified observations
- global update metadata advances only when a verified market or history observation changes
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import socket
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from provider_mappings import (
    ALPHA_VANTAGE_SERIES,
    BOK_SERIES,
    COINGECKO_SERIES,
    DERIVED_SERIES,
    FRED_SERIES,
    PROVIDER_PRIORITIES,
    ProviderMapping,
)


PLACEHOLDER = "—"
LOGGER = logging.getLogger("market-data")
REQUIRED_PROVENANCE_FIELDS = ("timestamp", "sourceName", "sourceUrl")
PUBLISHABLE_FIELDS = ("latest", "change1d", "change1w")
PROTECTED_VERIFIED_FIELDS = REQUIRED_PROVENANCE_FIELDS + PUBLISHABLE_FIELDS
ALLOWED_UPDATE_FIELDS = {
    "latest",
    "change1d",
    "change1w",
    "timestamp",
    "sourceName",
    "sourceUrl",
    "verified",
    "status",
    "interpretation",
    "unit",
    "changeUnit",
    "frequency",
    "derived",
    "inputs",
}


class ProviderError(RuntimeError):
    """Provider-specific failure that should not stop the full pipeline."""


@dataclass
class InstrumentUpdate:
    """A verified or explicitly sourced instrument update from a provider."""

    instrument_id: str
    fields: dict[str, Any]
    provider_name: str
    verified: bool = False
    reason: str = ""
    priority: int = 100


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


@dataclass(frozen=True)
class Observation:
    observation_date: str
    value: float


@dataclass
class DryRunRecord:
    provider: str
    instrument_id: str
    observation_date: str = PLACEHOLDER
    latest: Any = PLACEHOLDER
    change1d: Any = PLACEHOLDER
    change1w: Any = PLACEHOLDER
    source: str = PLACEHOLDER
    accepted: bool = False
    reason: str = ""


@dataclass
class ProviderResult:
    provider_name: str
    status: str
    updates: list[InstrumentUpdate] = field(default_factory=list)
    history_updates: list[HistoryUpdate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    records: list[DryRunRecord] = field(default_factory=list)
    rejected_count: int = 0
    message: str = ""

    @property
    def accepted_count(self) -> int:
        return len(self.updates)


@dataclass(frozen=True)
class ApplySummary:
    market_field_changes: int = 0
    history_point_changes: int = 0
    applied_instruments: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.market_field_changes > 0 or self.history_point_changes > 0


class JsonHttpClient:
    """Small bounded-retry JSON client using the Python standard library."""

    def __init__(self, timeout: float = 20.0, max_retries: int = 2, backoff_seconds: float = 0.75):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any] | list[Any]:
        request = Request(url, headers=headers or {})
        last_error: str | None = None

        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    status = getattr(response, "status", 200)
                    if status < 200 or status >= 300:
                        raise ProviderError(f"HTTP {status}")
                    raw = response.read()
                return json.loads(raw.decode("utf-8"))
            except HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                retryable = exc.code == 429 or 500 <= exc.code < 600
            except (TimeoutError, socket.timeout, URLError) as exc:
                last_error = exc.__class__.__name__
                retryable = True
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Invalid JSON response: {exc.msg}") from exc

            if retryable and attempt < self.max_retries:
                time.sleep(self.backoff_seconds * (attempt + 1))
                continue

            raise ProviderError(last_error or "Provider request failed")

        raise ProviderError(last_error or "Provider request failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update verified market data JSON files.")
    parser.add_argument("--dry-run", action="store_true", help="Validate providers without writing files.")
    parser.add_argument(
        "--provider",
        choices=("all", "fred", "bok", "alphavantage", "coingecko"),
        default="all",
        help="Run only one provider adapter.",
    )
    parser.add_argument("--data-file", default="data/market-data.json", help="Path to market data JSON.")
    parser.add_argument("--history-file", default="data/history.json", help="Path to history JSON.")
    parser.add_argument("--log-level", default="INFO", help="Python logging level.")
    parser.add_argument("--verbose", action="store_true", help="Print DEBUG logs and detailed dry-run records.")
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
        return value.strip() in {"", PLACEHOLDER, "."}
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


def parse_float(value: Any) -> float | None:
    if is_missing(value):
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def parse_int(value: Any) -> int | None:
    parsed = parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def round_market_value(value: float) -> float:
    if abs(value) >= 1_000_000:
        return round(value, 0)
    if abs(value) >= 100:
        return round(value, 2)
    return round(value, 4)


def round_change(value: float) -> float:
    rounded = round(value, 2)
    return int(rounded) if float(rounded).is_integer() else rounded


def pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round_change((current / previous - 1.0) * 100.0)


def value_change(current: float, previous: float, mapping: ProviderMapping) -> float | None:
    if mapping.value_type == "yield_percent":
        return round_change((current - previous) * 100.0)
    if mapping.value_type == "yield_spread_bp":
        return round_change(current - previous)
    if mapping.value_type in {"point_index", "percentage"}:
        return round_change(current - previous)
    return pct_change(current, previous)


def observation_timestamp(value: str) -> str:
    return clean_value(value)


def normal_date(value: str) -> str | None:
    cleaned = clean_value(value)
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y%m"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
        except (TypeError, ValueError):
            continue
        return parsed.date().isoformat()
    return None


def valid_history_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return True


def sanity_check(mapping: ProviderMapping, value: float) -> tuple[bool, str]:
    if not math.isfinite(value):
        return False, "value is not finite"
    if mapping.sanity_min is not None and value < mapping.sanity_min:
        return False, f"value {value} below sanity minimum {mapping.sanity_min}"
    if mapping.sanity_max is not None and value > mapping.sanity_max:
        return False, f"value {value} above sanity maximum {mapping.sanity_max}"
    return True, ""


def calculate_changes(observations: list[Observation], mapping: ProviderMapping) -> tuple[float | None, float | None]:
    if mapping.frequency != "daily":
        return None, None
    if len(observations) < 2:
        return None, None

    current = observations[-1].value
    change_1d = value_change(current, observations[-2].value, mapping)
    week_index = -(mapping.week_lag + 1)
    change_1w = value_change(current, observations[week_index].value, mapping) if len(observations) > mapping.week_lag else None
    return change_1d, change_1w


def build_updates_from_observations(
    mapping: ProviderMapping,
    observations: list[Observation],
    source_name: str,
) -> tuple[InstrumentUpdate | None, HistoryUpdate | None, DryRunRecord]:
    source = f"{source_name} <{mapping.source_url}>"
    if not observations:
        return (
            None,
            None,
            DryRunRecord(mapping.provider, mapping.instrument_id, source=source, reason="no verified observations returned"),
        )

    observations = sorted(observations, key=lambda item: item.observation_date)
    latest = observations[-1]
    ok, reason = sanity_check(mapping, latest.value)
    if not ok:
        return (
            None,
            None,
            DryRunRecord(
                mapping.provider,
                mapping.instrument_id,
                latest.observation_date,
                latest.value,
                source=source,
                reason=reason,
            ),
        )

    change_1d, change_1w = calculate_changes(observations, mapping)
    fields: dict[str, Any] = {
        "latest": round_market_value(latest.value),
        "timestamp": observation_timestamp(latest.observation_date),
        "sourceName": source_name,
        "sourceUrl": mapping.source_url,
        "unit": mapping.expected_unit,
        "changeUnit": mapping.change_unit,
        "frequency": mapping.frequency,
        "derived": not mapping.direct,
    }
    if change_1d is not None:
        fields["change1d"] = change_1d
    if change_1w is not None:
        fields["change1w"] = change_1w

    instrument_update = InstrumentUpdate(
        instrument_id=mapping.instrument_id,
        fields=fields,
        provider_name=mapping.provider,
        verified=True,
        priority=mapping.priority,
    )
    history_update = (
        HistoryUpdate(
            series_id=mapping.history_series_id,
            date=latest.observation_date,
            value=round_market_value(latest.value),
            timestamp=observation_timestamp(latest.observation_date),
            source_name=source_name,
            source_url=mapping.source_url,
            provider_name=mapping.provider,
            verified=True,
        )
        if mapping.history_series_id
        else None
    )
    record = DryRunRecord(
        mapping.provider,
        mapping.instrument_id,
        latest.observation_date,
        fields["latest"],
        fields.get("change1d", PLACEHOLDER),
        fields.get("change1w", PLACEHOLDER),
        source,
        accepted=True,
        reason="accepted",
    )
    return instrument_update, history_update, record


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


def apply_updates(data: dict[str, Any], updates: list[InstrumentUpdate]) -> tuple[int, tuple[str, ...]]:
    instruments = index_instruments(data)
    changed = 0
    applied: list[str] = []
    applied_priorities: dict[str, int] = {}
    applied_ids: set[str] = set()

    for update in sorted(updates, key=lambda item: item.priority):
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

        accepted_priority = applied_priorities.get(update.instrument_id)
        if accepted_priority is not None and update.priority > accepted_priority:
            LOGGER.info(
                "Skipping lower-priority update for %s from %s",
                update.instrument_id,
                update.provider_name,
            )
            continue

        instrument = instruments.get(update.instrument_id)
        if not instrument:
            LOGGER.warning("Ignoring update for unknown instrument id %s", update.instrument_id)
            continue

        applied_priorities[update.instrument_id] = update.priority
        update_changed = False
        for field_name, raw_incoming in update.fields.items():
            incoming = clean_value(raw_incoming)
            if field_name not in ALLOWED_UPDATE_FIELDS:
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
                update_changed = True

        if update.verified and not instrument.get("verified"):
            instrument["verified"] = True
            changed += 1
            update_changed = True

        if is_missing(update.fields.get("status")) and instrument.get("status") != "verified":
            instrument["status"] = "verified"
            changed += 1
            update_changed = True

        if update_changed and update.instrument_id not in applied_ids:
            applied.append(update.instrument_id)
            applied_ids.add(update.instrument_id)

    return changed, tuple(applied)


def history_update_has_provenance(update: HistoryUpdate) -> bool:
    return all(
        not is_missing(value)
        for value in (update.timestamp, update.source_name, update.source_url)
    ) and is_absolute_http_url(update.source_url)


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

        numeric_value = parse_float(update.value)
        if numeric_value is None:
            LOGGER.info("Skipping history update for %s because value is not numeric", update.series_id)
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

        points = [point for point in series.setdefault("points", []) if not is_missing(point.get("value"))]
        replacement = {
            "date": clean_value(update.date),
            "value": round_market_value(numeric_value),
            "timestamp": clean_value(update.timestamp),
            "sourceName": clean_value(update.source_name),
            "sourceUrl": clean_value(update.source_url),
            "verified": True,
        }

        points_by_date = {point.get("date"): point for point in points if point.get("date")}
        before = sorted_history_points(list(points_by_date.values()))
        points_by_date[replacement["date"]] = replacement
        after = sorted_history_points(list(points_by_date.values()))

        if before != after or series.get("points") != after:
            series["points"] = after
            changed += 1

    return changed


class ProviderAdapter:
    """Base class for market-data provider adapters."""

    name = "provider"
    provider_key = "provider"
    required_env: tuple[str, ...] = ()

    def __init__(self, client: JsonHttpClient | None = None):
        self.client = client or JsonHttpClient()

    def missing_env(self) -> list[str]:
        return [key for key in self.required_env if not os.environ.get(key)]

    def fetch_updates(self) -> ProviderResult:
        missing = self.missing_env()
        if missing:
            message = f"{self.name}: skipped — {', '.join(missing)} not configured"
            return ProviderResult(
                provider_name=self.name,
                status="skipped",
                message=message,
            )

        return self.fetch_verified_updates()

    def fetch_verified_updates(self) -> ProviderResult:
        return ProviderResult(
            provider_name=self.name,
            status="not_configured",
            errors=["Adapter is present, but no live provider mapping is configured."],
        )

    def result_from_records(
        self,
        updates: list[InstrumentUpdate],
        history_updates: list[HistoryUpdate],
        records: list[DryRunRecord],
        errors: list[str] | None = None,
    ) -> ProviderResult:
        errors = errors or []
        rejected = len([record for record in records if not record.accepted])
        if not records:
            rejected += len(errors)
        if updates and errors:
            status = "partial"
        elif updates:
            status = "ok"
        elif errors:
            status = "failed"
        else:
            status = "no_verified_updates"

        return ProviderResult(
            provider_name=self.name,
            status=status,
            updates=updates,
            history_updates=history_updates,
            errors=errors,
            records=records,
            rejected_count=rejected,
            message=f"{self.name}: {status} — {len(updates)} accepted, {rejected} rejected",
        )


class FredAdapter(ProviderAdapter):
    name = "FRED"
    provider_key = "fred"
    required_env = ("FRED_API_KEY",)

    def __init__(self, client: JsonHttpClient | None = None):
        super().__init__(client)
        self.api_key = os.environ.get("FRED_API_KEY", "")

    def fred_url(self, endpoint: str, params: dict[str, Any]) -> str:
        query = urlencode({**params, "api_key": self.api_key, "file_type": "json"})
        return f"https://api.stlouisfed.org/fred/{endpoint}?{query}"

    def verify_series_metadata(self, mapping: ProviderMapping) -> None:
        payload = self.client.get_json(
            self.fred_url("series", {"series_id": mapping.provider_symbol})
        )
        series_list = payload.get("seriess", []) if isinstance(payload, dict) else []
        if not any(series.get("id") == mapping.provider_symbol for series in series_list):
            raise ProviderError(f"metadata did not confirm FRED series {mapping.provider_symbol}")

    def observations(self, mapping: ProviderMapping) -> list[Observation]:
        payload = self.client.get_json(
            self.fred_url(
                "series/observations",
                {
                    "series_id": mapping.provider_symbol,
                    "sort_order": "desc",
                    "limit": 20,
                },
            )
        )
        rows = payload.get("observations", []) if isinstance(payload, dict) else []
        observations = []
        for row in rows:
            value = parse_float(row.get("value"))
            obs_date = normal_date(row.get("date", ""))
            if value is None or obs_date is None:
                continue
            observations.append(Observation(obs_date, value))
        return observations

    def fetch_verified_updates(self) -> ProviderResult:
        updates: list[InstrumentUpdate] = []
        history_updates: list[HistoryUpdate] = []
        records: list[DryRunRecord] = []
        errors: list[str] = []

        for mapping in FRED_SERIES.values():
            try:
                self.verify_series_metadata(mapping)
                observations = self.observations(mapping)
                source_name = f"FRED: {mapping.provider_symbol}"
                update, history_update, record = build_updates_from_observations(mapping, observations, source_name)
            except ProviderError as exc:
                errors.append(f"{mapping.instrument_id}: {exc}")
                record = DryRunRecord(
                    self.name,
                    mapping.instrument_id,
                    source=mapping.source_url,
                    reason=str(exc),
                )
                update = None
                history_update = None
            records.append(record)
            if update:
                updates.append(update)
            if history_update:
                history_updates.append(history_update)

        derived_updates, derived_history, derived_records = build_derived_updates(
            updates,
            {"us2s10s": ("ust10y", "ust2y")},
        )
        updates.extend(derived_updates)
        history_updates.extend(derived_history)
        records.extend(derived_records)

        return self.result_from_records(updates, history_updates, records, errors)


class BokEcosAdapter(ProviderAdapter):
    name = "BOK ECOS"
    provider_key = "bok"
    required_env = ("BOK_ECOS_API_KEY",)
    metadata_page_size = 100
    metadata_max_rows = 5000

    def __init__(self, client: JsonHttpClient | None = None):
        super().__init__(client)
        self.api_key = os.environ.get("BOK_ECOS_API_KEY", "")
        self.item_cache: dict[str, list[dict[str, Any]]] = {}

    def ecos_url(self, service: str, *segments: str) -> str:
        suffix = "/".join(segments)
        return f"https://ecos.bok.or.kr/api/{service}/{self.api_key}/json/kr/{suffix}"

    def check_ecos_error(self, payload: dict[str, Any]) -> None:
        result = payload.get("RESULT")
        if result:
            code = result.get("CODE", "UNKNOWN")
            message = result.get("MESSAGE", "ECOS returned an error")
            raise ProviderError(f"ECOS {code}: {message.strip()}")

    def statistic_items(self, stat_code: str) -> list[dict[str, Any]]:
        if stat_code in self.item_cache:
            return self.item_cache[stat_code]

        rows: list[dict[str, Any]] = []
        total_count: int | None = None
        start = 1

        while start <= self.metadata_max_rows:
            end = min(start + self.metadata_page_size - 1, self.metadata_max_rows)
            payload = self.client.get_json(self.ecos_url("StatisticItemList", str(start), str(end), stat_code))
            if not isinstance(payload, dict):
                raise ProviderError("ECOS metadata response was not an object")
            self.check_ecos_error(payload)

            section = payload.get("StatisticItemList", {})
            if not isinstance(section, dict):
                raise ProviderError("ECOS metadata response did not contain StatisticItemList")

            if total_count is None:
                total_count = parse_int(section.get("list_total_count"))

            batch = section.get("row", [])
            if isinstance(batch, dict):
                batch = [batch]
            if not isinstance(batch, list):
                raise ProviderError("ECOS metadata rows were malformed")
            rows.extend(row for row in batch if isinstance(row, dict))

            if total_count is not None and end >= total_count:
                break
            if total_count is None and len(batch) < self.metadata_page_size:
                break
            if not batch:
                break

            start = end + 1
        else:
            raise ProviderError("ECOS metadata pagination exceeded safe maximum")

        if total_count is not None and total_count > self.metadata_max_rows:
            raise ProviderError("ECOS metadata row count exceeded safe maximum")

        self.item_cache[stat_code] = rows
        return rows

    def verify_item_metadata(self, mapping: ProviderMapping) -> None:
        rows = self.statistic_items(mapping.stat_code or "")
        matched = [
            row for row in rows
            if row.get("ITEM_CODE") == mapping.item_code1 and row.get("CYCLE") == mapping.cycle
        ]
        if not matched:
            raise ProviderError(f"metadata did not confirm ECOS item {mapping.provider_symbol}")

    def observations(self, mapping: ProviderMapping) -> tuple[list[Observation], str]:
        end = date.today()
        start = end - timedelta(days=45)
        payload = self.client.get_json(
            self.ecos_url(
                "StatisticSearch",
                "1",
                "1000",
                mapping.stat_code or "",
                mapping.cycle or "D",
                start.strftime("%Y%m%d"),
                end.strftime("%Y%m%d"),
                mapping.item_code1 or "",
            )
        )
        if not isinstance(payload, dict):
            raise ProviderError("ECOS data response was not an object")
        self.check_ecos_error(payload)
        rows = payload.get("StatisticSearch", {}).get("row", [])
        observations = []
        source_name = f"BOK ECOS: {mapping.provider_symbol}"
        for row in rows:
            value = parse_float(row.get("DATA_VALUE"))
            obs_date = normal_date(row.get("TIME", ""))
            if row.get("STAT_NAME") and row.get("ITEM_NAME1"):
                source_name = f"BOK ECOS: {row['STAT_NAME']} / {row['ITEM_NAME1']}"
            if value is None or obs_date is None:
                continue
            observations.append(Observation(obs_date, value))
        return observations, source_name

    def fetch_verified_updates(self) -> ProviderResult:
        updates: list[InstrumentUpdate] = []
        history_updates: list[HistoryUpdate] = []
        records: list[DryRunRecord] = []
        errors: list[str] = []

        for mapping in BOK_SERIES.values():
            try:
                self.verify_item_metadata(mapping)
                observations, source_name = self.observations(mapping)
                update, history_update, record = build_updates_from_observations(mapping, observations, source_name)
            except ProviderError as exc:
                errors.append(f"{mapping.instrument_id}: {exc}")
                record = DryRunRecord(
                    self.name,
                    mapping.instrument_id,
                    source=mapping.source_url,
                    reason=str(exc),
                )
                update = None
                history_update = None
            records.append(record)
            if update:
                updates.append(update)
            if history_update:
                history_updates.append(history_update)

        derived_updates, derived_history, derived_records = build_derived_updates(
            updates,
            {"korea3s10s": ("ktb10y", "ktb3y")},
        )
        updates.extend(derived_updates)
        history_updates.extend(derived_history)
        records.extend(derived_records)

        return self.result_from_records(updates, history_updates, records, errors)


class AlphaVantageAdapter(ProviderAdapter):
    name = "Alpha Vantage"
    provider_key = "alphavantage"
    required_env = ("ALPHA_VANTAGE_API_KEY",)

    def __init__(self, client: JsonHttpClient | None = None):
        super().__init__(client)
        self.api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        self.index_catalog: set[str] | None = None

    def alpha_url(self, params: dict[str, Any]) -> str:
        return f"https://www.alphavantage.co/query?{urlencode({**params, 'apikey': self.api_key})}"

    def check_alpha_error(self, payload: dict[str, Any]) -> None:
        for key in ("Error Message", "Note", "Information"):
            if payload.get(key):
                raise ProviderError(str(payload[key]).strip())

    def parse_time_series(self, payload: dict[str, Any], mapping: ProviderMapping) -> list[Observation]:
        self.check_alpha_error(payload)
        series_key = next((key for key in payload if "Time Series" in key), "")
        if not series_key:
            raise ProviderError("Alpha Vantage response did not contain a time series")
        rows = payload.get(series_key, {})
        observations = []
        for row_date, row in rows.items():
            if not isinstance(row, dict):
                continue
            value = parse_float(row.get("4. close") or row.get("close"))
            obs_date = normal_date(row_date)
            if value is None or obs_date is None:
                continue
            observations.append(Observation(obs_date, value))
        return observations

    def parse_index_data(self, payload: dict[str, Any], mapping: ProviderMapping) -> list[Observation]:
        self.check_alpha_error(payload)
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise ProviderError("Alpha Vantage index response did not contain data rows")

        observations = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = parse_float(row.get("close") or row.get("4. close"))
            obs_date = normal_date(row.get("date") or row.get("timestamp") or row.get("time", ""))
            if value is None or obs_date is None:
                continue
            observations.append(Observation(obs_date, value))
        return observations

    def fetch_index_catalog(self) -> set[str]:
        if self.index_catalog is not None:
            return self.index_catalog
        payload = self.client.get_json(self.alpha_url({"function": "INDEX_CATALOG"}))
        if not isinstance(payload, dict):
            self.index_catalog = set()
            return self.index_catalog
        self.check_alpha_error(payload)
        rows = payload.get("data") or payload.get("indices") or payload.get("Index Catalog") or []
        symbols = {
            clean_value(row.get("symbol") or row.get("Symbol") or row.get("ticker") or row.get("Ticker"))
            for row in rows
            if isinstance(row, dict)
        }
        self.index_catalog = {symbol for symbol in symbols if isinstance(symbol, str) and symbol}
        return self.index_catalog

    def verify_index_symbol(self, mapping: ProviderMapping) -> None:
        catalog = self.fetch_index_catalog()
        if mapping.symbol not in catalog:
            raise ProviderError(f"INDEX_CATALOG did not confirm actual index symbol {mapping.symbol}")

    def observations(self, mapping: ProviderMapping) -> list[Observation]:
        if mapping.function == "FX_DAILY":
            payload = self.client.get_json(
                self.alpha_url(
                    {
                        "function": "FX_DAILY",
                        "from_symbol": mapping.from_symbol,
                        "to_symbol": mapping.to_symbol,
                        "outputsize": "compact",
                    }
                )
            )
            if not isinstance(payload, dict):
                raise ProviderError("Alpha Vantage FX response was not an object")
            return self.parse_time_series(payload, mapping)

        if mapping.function == "INDEX_DATA":
            self.verify_index_symbol(mapping)
            payload = self.client.get_json(
                self.alpha_url(
                    {
                        "function": "INDEX_DATA",
                        "symbol": mapping.symbol,
                        "interval": "daily",
                    }
                )
            )
            if not isinstance(payload, dict):
                raise ProviderError("Alpha Vantage index response was not an object")
            return self.parse_index_data(payload, mapping)

        raise ProviderError(f"Unsupported Alpha Vantage function {mapping.function}")

    def fetch_verified_updates(self) -> ProviderResult:
        updates: list[InstrumentUpdate] = []
        history_updates: list[HistoryUpdate] = []
        records: list[DryRunRecord] = []
        errors: list[str] = []

        for mapping in ALPHA_VANTAGE_SERIES.values():
            try:
                observations = self.observations(mapping)
                source_name = f"Alpha Vantage: {mapping.function} {mapping.provider_symbol}"
                update, history_update, record = build_updates_from_observations(mapping, observations, source_name)
            except ProviderError as exc:
                errors.append(f"{mapping.instrument_id}: {exc}")
                record = DryRunRecord(
                    self.name,
                    mapping.instrument_id,
                    source=mapping.source_url,
                    reason=str(exc),
                )
                update = None
                history_update = None
            records.append(record)
            if update:
                updates.append(update)
            if history_update:
                history_updates.append(history_update)

        return self.result_from_records(updates, history_updates, records, errors)


class CoinGeckoAdapter(ProviderAdapter):
    name = "CoinGecko"
    provider_key = "coingecko"
    required_env = ("COINGECKO_API_KEY",)

    def __init__(self, client: JsonHttpClient | None = None):
        super().__init__(client)
        self.api_key = os.environ.get("COINGECKO_API_KEY", "")
        self.base_url = "https://api.coingecko.com/api/v3"
        self.header_name = "x-cg-demo-api-key"

    def headers(self) -> dict[str, str]:
        return {self.header_name: self.api_key}

    def coingecko_url(self, endpoint: str, params: dict[str, Any] | None = None) -> str:
        query = f"?{urlencode(params)}" if params else ""
        return f"{self.base_url}{endpoint}{query}"

    def check_coingecko_error(self, payload: dict[str, Any] | list[Any]) -> None:
        if isinstance(payload, dict) and payload.get("status", {}).get("error_message"):
            raise ProviderError(payload["status"]["error_message"])
        if isinstance(payload, dict) and payload.get("error"):
            raise ProviderError(str(payload["error"]))

    def market_chart_observations(self, mapping: ProviderMapping) -> list[Observation]:
        payload = self.client.get_json(
            self.coingecko_url(
                f"/coins/{mapping.coingecko_id}/market_chart",
                {"vs_currency": "usd", "days": "10", "interval": "daily"},
            ),
            self.headers(),
        )
        self.check_coingecko_error(payload)
        prices = payload.get("prices", []) if isinstance(payload, dict) else []
        by_date: dict[str, float] = {}
        for point in prices:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            timestamp_ms, value = point[:2]
            parsed_value = parse_float(value)
            if parsed_value is None:
                continue
            timestamp_value = parse_float(timestamp_ms)
            if timestamp_value is None:
                continue
            obs_date = datetime.fromtimestamp(timestamp_value / 1000, timezone.utc).date().isoformat()
            by_date[obs_date] = parsed_value
        return [Observation(obs_date, value) for obs_date, value in sorted(by_date.items())]

    def global_updates(self) -> tuple[list[InstrumentUpdate], list[HistoryUpdate], list[DryRunRecord]]:
        payload = self.client.get_json(self.coingecko_url("/global"), self.headers())
        self.check_coingecko_error(payload)
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        updated_at = data.get("updated_at")
        if not isinstance(updated_at, (int, float)):
            raise ProviderError("CoinGecko global response did not include updated_at")
        timestamp = datetime.fromtimestamp(updated_at, timezone.utc).isoformat()
        obs_date = timestamp[:10]
        items = [
            ("total_crypto_mcap", data.get("total_market_cap", {}).get("usd")),
            ("btc_dominance", data.get("market_cap_percentage", {}).get("btc")),
        ]
        updates: list[InstrumentUpdate] = []
        history_updates: list[HistoryUpdate] = []
        records: list[DryRunRecord] = []

        for instrument_id, raw_value in items:
            mapping = COINGECKO_SERIES[instrument_id]
            value = parse_float(raw_value)
            source_name = f"CoinGecko: {mapping.provider_symbol}"
            source = f"{source_name} <{mapping.source_url}>"
            if value is None:
                records.append(DryRunRecord(self.name, instrument_id, source=source, reason="missing global value"))
                continue
            ok, reason = sanity_check(mapping, value)
            if not ok:
                records.append(DryRunRecord(self.name, instrument_id, obs_date, value, source=source, reason=reason))
                continue
            fields = {
                "latest": round_market_value(value),
                "timestamp": timestamp,
                "sourceName": source_name,
                "sourceUrl": mapping.source_url,
                "unit": mapping.expected_unit,
                "changeUnit": mapping.change_unit,
                "frequency": mapping.frequency,
                "derived": False,
            }
            updates.append(
                InstrumentUpdate(
                    instrument_id=instrument_id,
                    fields=fields,
                    provider_name=self.name,
                    verified=True,
                    priority=mapping.priority,
                )
            )
            if mapping.history_series_id:
                history_updates.append(
                    HistoryUpdate(
                        mapping.history_series_id,
                        obs_date,
                        fields["latest"],
                        timestamp,
                        source_name,
                        mapping.source_url,
                        self.name,
                        True,
                    )
                )
            records.append(
                DryRunRecord(
                    self.name,
                    instrument_id,
                    obs_date,
                    fields["latest"],
                    source=source,
                    accepted=True,
                    reason="accepted",
                )
            )

        return updates, history_updates, records

    def fetch_verified_updates(self) -> ProviderResult:
        updates: list[InstrumentUpdate] = []
        history_updates: list[HistoryUpdate] = []
        records: list[DryRunRecord] = []
        errors: list[str] = []

        for instrument_id in ("btcusd", "ethusd"):
            mapping = COINGECKO_SERIES[instrument_id]
            try:
                observations = self.market_chart_observations(mapping)
                source_name = f"CoinGecko: {mapping.provider_symbol}"
                update, history_update, record = build_updates_from_observations(mapping, observations, source_name)
            except ProviderError as exc:
                errors.append(f"{mapping.instrument_id}: {exc}")
                record = DryRunRecord(
                    self.name,
                    mapping.instrument_id,
                    source=mapping.source_url,
                    reason=str(exc),
                )
                update = None
                history_update = None
            records.append(record)
            if update:
                updates.append(update)
            if history_update:
                history_updates.append(history_update)

        try:
            global_updates, global_history, global_records = self.global_updates()
            updates.extend(global_updates)
            history_updates.extend(global_history)
            records.extend(global_records)
        except ProviderError as exc:
            errors.append(f"crypto_global: {exc}")
            records.append(DryRunRecord(self.name, "crypto_global", source=COINGECKO_SERIES["total_crypto_mcap"].source_url, reason=str(exc)))

        return self.result_from_records(updates, history_updates, records, errors)


def build_derived_updates(
    direct_updates: list[InstrumentUpdate],
    recipes: dict[str, tuple[str, str]],
) -> tuple[list[InstrumentUpdate], list[HistoryUpdate], list[DryRunRecord]]:
    updates_by_id = {update.instrument_id: update for update in direct_updates if update.verified}
    derived_updates: list[InstrumentUpdate] = []
    history_updates: list[HistoryUpdate] = []
    records: list[DryRunRecord] = []

    for derived_id, (long_id, short_id) in recipes.items():
        mapping = DERIVED_SERIES[derived_id]
        long_update = updates_by_id.get(long_id)
        short_update = updates_by_id.get(short_id)
        source = f"{mapping.provider_symbol} <{mapping.source_url}>"

        if not long_update or not short_update:
            records.append(
                DryRunRecord(
                    mapping.provider,
                    derived_id,
                    source=source,
                    reason="required verified inputs are missing",
                )
            )
            continue

        long_date = str(long_update.fields.get("timestamp", ""))[:10]
        short_date = str(short_update.fields.get("timestamp", ""))[:10]
        if long_date != short_date:
            records.append(
                DryRunRecord(
                    mapping.provider,
                    derived_id,
                    source=source,
                    reason="input observation dates do not match",
                )
            )
            continue

        long_value = parse_float(long_update.fields.get("latest"))
        short_value = parse_float(short_update.fields.get("latest"))
        if long_value is None or short_value is None:
            records.append(DryRunRecord(mapping.provider, derived_id, source=source, reason="input values are missing"))
            continue

        spread = (long_value - short_value) * 100.0
        ok, reason = sanity_check(mapping, spread)
        if not ok:
            records.append(DryRunRecord(mapping.provider, derived_id, long_date, spread, source=source, reason=reason))
            continue

        source_name = f"Derived from {long_update.fields['sourceName']} and {short_update.fields['sourceName']}"
        fields = {
            "latest": round_change(spread),
            "timestamp": long_date,
            "sourceName": source_name,
            "sourceUrl": mapping.source_url,
            "unit": mapping.expected_unit,
            "changeUnit": mapping.change_unit,
            "frequency": mapping.frequency,
            "derived": True,
            "inputs": [
                {
                    "instrumentId": long_id,
                    "timestamp": long_update.fields.get("timestamp"),
                    "sourceName": long_update.fields.get("sourceName"),
                    "sourceUrl": long_update.fields.get("sourceUrl"),
                },
                {
                    "instrumentId": short_id,
                    "timestamp": short_update.fields.get("timestamp"),
                    "sourceName": short_update.fields.get("sourceName"),
                    "sourceUrl": short_update.fields.get("sourceUrl"),
                },
            ],
        }
        derived_updates.append(
            InstrumentUpdate(
                derived_id,
                fields,
                mapping.provider,
                verified=True,
                priority=mapping.priority,
            )
        )
        if mapping.history_series_id:
            history_updates.append(
                HistoryUpdate(
                    mapping.history_series_id,
                    long_date,
                    fields["latest"],
                    long_date,
                    source_name,
                    mapping.source_url,
                    mapping.provider,
                    True,
                )
            )
        records.append(
            DryRunRecord(
                mapping.provider,
                derived_id,
                long_date,
                fields["latest"],
                source=source,
                accepted=True,
                reason="accepted",
            )
        )

    return derived_updates, history_updates, records


def provider_adapters(selected_provider: str = "all") -> list[ProviderAdapter]:
    adapters: list[ProviderAdapter] = [
        FredAdapter(),
        BokEcosAdapter(),
        AlphaVantageAdapter(),
        CoinGeckoAdapter(),
    ]
    if selected_provider == "all":
        return adapters
    return [adapter for adapter in adapters if adapter.provider_key == selected_provider]


def provider_metadata(results: list[ProviderResult], updated_at: str) -> dict[str, dict[str, Any]]:
    return {
        result.provider_name: {
            "status": result.status,
            "updatedAt": updated_at,
            "numberOfSuccessfulUpdates": result.accepted_count,
            "numberOfRejectedUpdates": result.rejected_count,
            "message": result.message,
        }
        for result in results
    }


def print_dry_run(results: list[ProviderResult]) -> None:
    for result in results:
        print(result.message or f"{result.provider_name}: {result.status}")
        for error in result.errors:
            print(f"  {error}")
        for record in result.records:
            state = "accepted" if record.accepted else "rejected"
            print(
                "  "
                f"provider={record.provider} "
                f"instrument={record.instrument_id} "
                f"observationDate={record.observation_date} "
                f"latest={record.latest} "
                f"change1d={record.change1d} "
                f"change1w={record.change1w} "
                f"source={record.source} "
                f"state={state} "
                f"reason={record.reason}"
            )


def main() -> int:
    args = parse_args()
    log_level = "DEBUG" if args.verbose else args.log_level.upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(levelname)s %(message)s",
    )

    data_path = Path(args.data_file)
    history_path = Path(args.history_file)
    data = load_json(data_path)
    history = load_json(history_path)

    results: list[ProviderResult] = []
    updates: list[InstrumentUpdate] = []
    history_updates: list[HistoryUpdate] = []

    for adapter in provider_adapters(args.provider):
        try:
            result = adapter.fetch_updates()
        except Exception as exc:  # noqa: BLE001 - adapters should never stop the whole pipeline.
            LOGGER.exception("Provider %s failed", adapter.name)
            result = ProviderResult(
                adapter.name,
                "failed",
                errors=[exc.__class__.__name__],
                rejected_count=1,
                message=f"{adapter.name}: failed — {exc.__class__.__name__}",
            )

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
        print_dry_run(results)
        LOGGER.info("Dry run complete. No files were written.")
        return 0

    market_changed, applied_instruments = apply_updates(data, updates)
    history_changed = apply_history_updates(history, history_updates)
    summary = ApplySummary(market_changed, history_changed, applied_instruments)
    if not summary.changed:
        LOGGER.info("No verified market or history observations changed. Existing files left untouched.")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    metadata = data.setdefault("metadata", {})
    metadata["asOf"] = now
    metadata["lastDataChangeAt"] = now
    metadata["lastSuccessfulUpdate"] = now
    metadata["lastPipelineRunAt"] = now
    metadata["status"] = "updated"
    metadata["providers"] = provider_metadata(results, now)
    metadata["providerStatus"] = [
        {"name": result.provider_name, "status": result.status, "errors": result.errors}
        for result in results
    ]

    write_json(data_path, data)
    if history_changed:
        write_json(history_path, history)
    LOGGER.info(
        "Wrote verified updates: %s market field changes, %s history point changes.",
        market_changed,
        history_changed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
