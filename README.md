# Global Markets Macro Journal

Personal Global Markets / FICC / Macro research terminal and daily journal.

The site is static, GitHub Pages-compatible, and intentionally placeholder-first:
unverified market values must remain `—`.

## Site Structure

- `index.html` - Static macro terminal shell.
- `styles.css` - Responsive institutional dashboard styling.
- `app.js` - Client-side rendering for the dashboard, archive, charts, calendar, glossary, and methodology.
- `data/market-data.json` - Current dashboard schema and placeholder market instruments.
- `data/history.json` - Historical chart schema with verified numeric points only.
- `data/archive.json` - Daily briefing archive index.
- `data/daily/YYYY-MM-DD.json` - Individual daily briefing files.
- `docs/data-sources.md` - Provider mappings, methodology, and live-capable coverage.
- `scripts/provider_mappings.py` - Auditable provider/series registry.
- `scripts/update_market_data.py` - Verified provider-adapter market data update pipeline.
- `scripts/validate_market_data.py` - Local and CI market-data integrity checks.
- `tests/test_market_data.py` - Mocked provider/update safety tests.
- `.github/workflows/pages.yml` - GitHub Pages deployment workflow.
- `.github/workflows/update-market-data.yml` - Scheduled market data refresh workflow.
- `.nojekyll` - Ensures GitHub Pages serves static files directly.

## Current Functionality

- Compact Today dashboard with macro regime, 3-5 cross-asset signals, and global data status.
- Global, Korea, and Digital Assets market dashboards with latest, 1D, 1W, timestamp, source, status, and interpretation fields.
- Asset class boards for rates, Korea rates, FX, equities/volatility, credit, and commodities.
- Exactly five Top Macro Stories slots from the current daily briefing.
- Chart panels for UST 2Y/10Y, US 2s10s, DXY/USDKRW, normalized equities, VIX/MOVE, and normalized commodities.
- Macro calendar with status, importance, actual, consensus, previous, surprise, market sensitivity, and source fields.
- Positioning / Flows / Market Pricing section split into Hard Data and Market Inference.
- Digital Assets section with BTC and ETH core cards, optional crypto indicators, and crypto signal classification.
- Wide desktop briefing reader with mobile stacked layout.
- FICC glossary and source hierarchy methodology.

## Data Schema

Each instrument in `data/market-data.json` supports:

```json
{
  "id": "ust10y",
  "name": "US Treasury 10Y",
  "assetClass": "Rates",
  "region": "US",
  "unit": "%",
  "latest": "—",
  "change1d": "—",
  "change1w": "—",
  "changeUnit": "bp",
  "timestamp": "—",
  "sourceName": "—",
  "sourceUrl": "—",
  "verified": false,
  "status": "unverified",
  "interpretation": "—"
}
```

Historical series in `data/history.json` use numeric `value` fields only when
verified. Unknown observations are omitted from history rather than stored as
placeholder points or zero.

## Data Status Rules

The visible global status uses ISO timestamps:

- No `lastSuccessfulUpdate`: `SETUP / DATA PIPELINE PENDING`
- Last successful update older than 24 hours: `STALE DATA`
- Last successful update within 24 hours: `DATA CURRENT`

## Source Discipline

Permanent rule:

`Observed Market Data ≠ Reported Driver ≠ Model Interpretation`

Do not imply causality from price co-movement alone. Label observed facts,
reported drivers, and your own interpretation as separate evidence layers.

Source hierarchy:

1. Primary official sources
2. Exchanges / regulators / issuers
3. Reliable market-data providers
4. Reputable financial media
5. Specialist research / analytics

## Phase 3A Live Market Data Setup

The market-data updater has live-capable adapters for FRED, BOK ECOS, Alpha
Vantage, and CoinGecko. It does not scrape restricted/proprietary sites and does
not embed API keys.

Required environment variables:

- `FRED_API_KEY`
- `BOK_ECOS_API_KEY`
- `ALPHA_VANTAGE_API_KEY`
- `COINGECKO_API_KEY`

Run local dry runs:

```bash
python scripts/update_market_data.py --dry-run
python scripts/update_market_data.py --provider fred --dry-run
python scripts/update_market_data.py --provider bok --dry-run
python scripts/update_market_data.py --provider alphavantage --dry-run
python scripts/update_market_data.py --provider coingecko --dry-run
python scripts/update_market_data.py --provider fred --dry-run --verbose
```

If secrets are missing, providers skip gracefully. If a provider fails, the
pipeline logs the failure and preserves existing values.

Run local validation:

```bash
python -m pip install pytest
python -m json.tool data/market-data.json >/dev/null
python -m json.tool data/history.json >/dev/null
python scripts/validate_market_data.py
python -m py_compile scripts/update_market_data.py scripts/provider_mappings.py scripts/validate_market_data.py
python -m pytest tests/test_market_data.py
node --check app.js
```

GitHub repository secrets should be configured with the same four names above.
Do not commit `.env` files or secret values.

See `docs/data-sources.md` for exact series IDs, history-upsert rules, provider
priority, source-provenance requirements, and placeholder limitations.

## GitHub Actions

`update-market-data.yml` runs once daily at `22:00 UTC`, equivalent to roughly
`07:00 Asia/Seoul`, and can also be started with `workflow_dispatch`.

The update workflow validates JSON and only commits when `data/market-data.json`
or `data/history.json` changes. It always checks out `main` and pushes verified
production data to `origin main`.

The Pages workflow deploys for normal pushes to `main`, manual dispatches, and
successful completion of the `Update market data` workflow. For workflow-run
deployments it checks out latest `main`, so a scheduled data commit can redeploy
even when GitHub's token recursion protections suppress a push-triggered Pages
run.
