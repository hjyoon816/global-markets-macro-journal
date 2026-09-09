import json
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import update_market_data as updater  # noqa: E402
from provider_mappings import ALPHA_VANTAGE_SERIES, FRED_SERIES  # noqa: E402


SOURCE_URL = "https://example.com/source"


def minimal_market_doc(verified=False):
    return {
        "metadata": {
            "asOf": "2026-09-10T00:00:00+09:00",
            "lastSuccessfulUpdate": None,
            "status": "setup",
        },
        "instruments": [
            {
                "id": "ust10y",
                "name": "US Treasury 10Y",
                "latest": 4.1 if verified else "—",
                "change1d": 1 if verified else "—",
                "change1w": 5 if verified else "—",
                "timestamp": "2026-09-08" if verified else "—",
                "sourceName": "Existing source" if verified else "—",
                "sourceUrl": SOURCE_URL if verified else "—",
                "verified": verified,
                "status": "verified" if verified else "unverified",
            }
        ],
    }


def minimal_history_doc(points=None):
    return {
        "series": [
            {
                "id": "ust10y",
                "name": "US Treasury 10Y",
                "unit": "%",
                "frequency": "daily",
                "sourceName": "—",
                "sourceUrl": "—",
                "points": points or [],
            }
        ]
    }


def verified_update(instrument_id="ust10y", fields=None):
    return updater.InstrumentUpdate(
        instrument_id=instrument_id,
        provider_name="Test",
        verified=True,
        fields=fields
        or {
            "latest": 4.25,
            "timestamp": "2026-09-09",
            "sourceName": "Test source",
            "sourceUrl": SOURCE_URL,
        },
    )


def history_update(value=4.25, date="2026-09-09"):
    return updater.HistoryUpdate(
        series_id="ust10y",
        date=date,
        value=value,
        timestamp=date,
        source_name="Test source",
        source_url=SOURCE_URL,
        provider_name="Test",
        verified=True,
    )


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_unverified_updates_are_rejected():
    data = minimal_market_doc()
    update = verified_update()
    update.verified = False

    changed, applied = updater.apply_updates(data, [update])

    assert changed == 0
    assert applied == ()
    assert data["instruments"][0]["latest"] == "—"


def test_missing_provenance_is_rejected():
    data = minimal_market_doc()
    update = verified_update(fields={"latest": 4.25, "timestamp": "2026-09-09", "sourceName": "Test source"})

    changed, applied = updater.apply_updates(data, [update])

    assert changed == 0
    assert applied == ()


def test_malformed_source_url_is_rejected():
    data = minimal_market_doc()
    update = verified_update(fields={"latest": 4.25, "timestamp": "2026-09-09", "sourceName": "Test source", "sourceUrl": "javascript:alert(1)"})

    changed, applied = updater.apply_updates(data, [update])

    assert changed == 0
    assert applied == ()


def test_verified_update_is_accepted():
    data = minimal_market_doc()

    changed, applied = updater.apply_updates(data, [verified_update()])

    instrument = data["instruments"][0]
    assert changed > 0
    assert applied == ("ust10y",)
    assert instrument["latest"] == 4.25
    assert instrument["verified"] is True
    assert instrument["status"] == "verified"


def test_missing_provider_api_key_skips_safely(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    result = updater.FredAdapter().fetch_updates()

    assert result.status == "skipped"
    assert "FRED_API_KEY not configured" in result.message


def test_bad_numeric_data_is_rejected():
    update, history_update, record = updater.build_updates_from_observations(
        FRED_SERIES["ust10y"],
        [updater.Observation("2026-09-09", 999.0)],
        "FRED: DGS10",
    )

    assert update is None
    assert history_update is None
    assert record.accepted is False
    assert "above sanity maximum" in record.reason


def test_history_append():
    history = minimal_history_doc()

    changed = updater.apply_history_updates(history, [history_update()])

    assert changed == 1
    assert history["series"][0]["points"] == [
        {
            "date": "2026-09-09",
            "value": 4.25,
            "timestamp": "2026-09-09",
            "sourceName": "Test source",
            "sourceUrl": SOURCE_URL,
            "verified": True,
        }
    ]


def test_same_day_history_replace():
    history = minimal_history_doc(
        [
            {
                "date": "2026-09-09",
                "value": 4.1,
                "timestamp": "2026-09-09",
                "sourceName": "Old source",
                "sourceUrl": SOURCE_URL,
                "verified": True,
            }
        ]
    )

    changed = updater.apply_history_updates(history, [history_update(4.3)])

    assert changed == 1
    assert len(history["series"][0]["points"]) == 1
    assert history["series"][0]["points"][0]["value"] == 4.3


def test_duplicate_history_dates_are_collapsed():
    history = minimal_history_doc(
        [
            {"date": "2026-09-09", "value": 4.0},
            {"date": "2026-09-09", "value": 4.1},
        ]
    )

    updater.apply_history_updates(history, [history_update(4.2)])

    points = history["series"][0]["points"]
    assert len(points) == 1
    assert points[0]["date"] == "2026-09-09"
    assert points[0]["value"] == 4.2


def test_history_chronological_sorting():
    history = minimal_history_doc(
        [
            {
                "date": "2026-09-10",
                "value": 4.4,
                "timestamp": "2026-09-10",
                "sourceName": "Test source",
                "sourceUrl": SOURCE_URL,
                "verified": True,
            }
        ]
    )

    updater.apply_history_updates(history, [history_update(4.2, "2026-09-09")])

    assert [point["date"] for point in history["series"][0]["points"]] == ["2026-09-09", "2026-09-10"]


def test_verified_values_are_not_overwritten_by_missing_incoming_fields():
    data = minimal_market_doc(verified=True)
    update = verified_update(
        fields={
            "latest": 4.25,
            "change1d": "—",
            "change1w": "—",
            "timestamp": "2026-09-09",
            "sourceName": "Test source",
            "sourceUrl": SOURCE_URL,
        }
    )

    updater.apply_updates(data, [update])

    instrument = data["instruments"][0]
    assert instrument["latest"] == 4.25
    assert instrument["change1d"] == 1
    assert instrument["change1w"] == 5


def test_yield_1d_change_is_basis_points():
    change_1d, change_1w = updater.calculate_changes(
        [updater.Observation("2026-09-08", 4.25), updater.Observation("2026-09-09", 4.31)],
        FRED_SERIES["ust10y"],
    )

    assert change_1d == 6
    assert change_1w is None


def test_percentage_1w_change_uses_configured_lag():
    observations = [
        updater.Observation("2026-09-01", 1.00),
        updater.Observation("2026-09-02", 1.02),
        updater.Observation("2026-09-03", 1.04),
        updater.Observation("2026-09-04", 1.06),
        updater.Observation("2026-09-08", 1.08),
        updater.Observation("2026-09-09", 1.10),
    ]

    change_1d, change_1w = updater.calculate_changes(observations, ALPHA_VANTAGE_SERIES["eurusd"])

    assert change_1d == 1.85
    assert change_1w == 10


def test_derived_2s10s_requires_verified_inputs():
    ust10y = verified_update("ust10y", {"latest": 4.5, "timestamp": "2026-09-09", "sourceName": "FRED: DGS10", "sourceUrl": SOURCE_URL})
    ust2y = verified_update("ust2y", {"latest": 4.1, "timestamp": "2026-09-09", "sourceName": "FRED: DGS2", "sourceUrl": SOURCE_URL})
    updates, history_updates, records = updater.build_derived_updates([ust10y, ust2y], {"us2s10s": ("ust10y", "ust2y")})

    assert updates[0].instrument_id == "us2s10s"
    assert updates[0].fields["latest"] == 40
    assert history_updates[0].series_id == "us2s10s"
    assert records[0].accepted is True

    ust2y.verified = False
    updates, history_updates, records = updater.build_derived_updates([ust10y, ust2y], {"us2s10s": ("ust10y", "ust2y")})
    assert updates == []
    assert history_updates == []
    assert records[0].accepted is False


def test_latest_observation_uses_provider_date_not_calendar_date():
    update, _, _ = updater.build_updates_from_observations(
        FRED_SERIES["ust10y"],
        [updater.Observation("2026-09-04", 4.2), updater.Observation("2026-09-05", 4.25)],
        "FRED: DGS10",
    )

    assert update.fields["timestamp"] == "2026-09-05"


def test_provider_failure_does_not_block_other_updates(monkeypatch, tmp_path):
    data_path = tmp_path / "market-data.json"
    history_path = tmp_path / "history.json"
    write_json(data_path, minimal_market_doc())
    write_json(history_path, minimal_history_doc())

    class FailingAdapter:
        name = "Failing"

        def fetch_updates(self):
            raise RuntimeError("not exposed")

    class GoodAdapter:
        name = "Good"

        def fetch_updates(self):
            return updater.ProviderResult(
                "Good",
                "ok",
                updates=[verified_update()],
                message="Good: ok",
            )

    monkeypatch.setattr(updater, "provider_adapters", lambda _: [FailingAdapter(), GoodAdapter()])
    monkeypatch.setattr(
        sys,
        "argv",
        ["update_market_data.py", "--data-file", str(data_path), "--history-file", str(history_path)],
    )

    assert updater.main() == 0
    data = read_json(data_path)
    assert data["instruments"][0]["latest"] == 4.25
    assert data["metadata"]["lastSuccessfulUpdate"]
    assert data["metadata"]["providerStatus"][0]["status"] == "failed"


def test_zero_accepted_updates_do_not_advance_metadata(monkeypatch, tmp_path):
    data_path = tmp_path / "market-data.json"
    history_path = tmp_path / "history.json"
    original = minimal_market_doc()
    original["metadata"]["lastSuccessfulUpdate"] = None
    write_json(data_path, original)
    write_json(history_path, minimal_history_doc())

    class EmptyAdapter:
        name = "Empty"

        def fetch_updates(self):
            return updater.ProviderResult("Empty", "no_verified_updates", message="Empty: no verified updates")

    monkeypatch.setattr(updater, "provider_adapters", lambda _: [EmptyAdapter()])
    monkeypatch.setattr(
        sys,
        "argv",
        ["update_market_data.py", "--data-file", str(data_path), "--history-file", str(history_path)],
    )

    assert updater.main() == 0
    data = read_json(data_path)
    assert data["metadata"]["lastSuccessfulUpdate"] is None
    assert "providers" not in data["metadata"]
