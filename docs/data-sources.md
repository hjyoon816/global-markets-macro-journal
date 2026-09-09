# Data Sources And Methodology

Phase 3A connects verified market-data providers only. Missing, stale, malformed,
or unverified observations stay as `—`; the pipeline must not fabricate values
to make the dashboard look complete.

## Provider Registry

All auditable mappings live in `scripts/provider_mappings.py`.

| Instrument | Internal ID | Provider | Provider series/symbol | Direct/Derived | Frequency | Unit | Source URL | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Effective Fed Funds Rate (DFF proxy) | `fed_target_range` | FRED | `DFF` | Direct | Daily | `%` | https://fred.stlouisfed.org/series/DFF | DFF is used as the verified effective Fed Funds proxy for the policy-rate slot. |
| US Treasury 2Y | `ust2y` | FRED | `DGS2` | Direct | Daily | `%` | https://fred.stlouisfed.org/series/DGS2 | Series metadata is checked before observations are accepted. |
| US Treasury 10Y | `ust10y` | FRED | `DGS10` | Direct | Daily | `%` | https://fred.stlouisfed.org/series/DGS10 | Series metadata is checked before observations are accepted. |
| US Treasury 30Y | `ust30y` | FRED | `DGS30` | Direct | Daily | `%` | https://fred.stlouisfed.org/series/DGS30 | Series metadata is checked before observations are accepted. |
| US 2s10s | `us2s10s` | Derived from FRED | `DGS10-DGS2` | Derived | Daily | `bp` | https://fred.stlouisfed.org/graph/?id=DGS10,DGS2 | Calculated only when both inputs are verified for the same observation date. |
| US 10Y real yield | `us10y_real_yield` | FRED | `DFII10` | Direct | Daily | `%` | https://fred.stlouisfed.org/series/DFII10 | Series metadata is checked before observations are accepted. |
| US 10Y breakeven inflation | `us10y_breakeven` | FRED | `T10YIE` | Direct | Daily | `%` | https://fred.stlouisfed.org/series/T10YIE | Series metadata is checked before observations are accepted. |
| VIX | `vix` | FRED | `VIXCLS` | Direct | Daily | `index` | https://fred.stlouisfed.org/series/VIXCLS | Stored as level; daily changes are points. |
| WTI | `wti` | FRED | `DCOILWTICO` | Direct | Daily | `USD/bbl` | https://fred.stlouisfed.org/series/DCOILWTICO | Allows negative WTI prints but rejects obvious malformed extremes. |
| Brent | `brent` | FRED | `DCOILBRENTEU` | Direct | Daily | `USD/bbl` | https://fred.stlouisfed.org/series/DCOILBRENTEU | Stored as provider-documented price. |
| Gold | `gold` | FRED | `GOLDAMGBD228NLBM` | Direct | Daily | `USD/oz` | https://fred.stlouisfed.org/series/GOLDAMGBD228NLBM | Stored as provider-documented price. |
| Copper | `copper` | FRED | `PCOPPUSDM` | Direct | Monthly | `USD/metric ton` | https://fred.stlouisfed.org/series/PCOPPUSDM | Monthly IMF global copper price via FRED; 1D/1W are not calculated. |
| BOK base rate | `bok_base_rate` | BOK ECOS | `722Y001:0101000` | Direct | Daily | `%` | https://ecos.bok.or.kr/api/ | Confirmed by ECOS metadata as `한국은행 기준금리`. |
| KTB 3Y | `ktb3y` | BOK ECOS | `817Y002:010200000` | Direct | Daily | `%` | https://ecos.bok.or.kr/api/ | Confirmed by ECOS metadata as `국고채(3년)`. |
| KTB 10Y | `ktb10y` | BOK ECOS | `817Y002:010210000` | Direct | Daily | `%` | https://ecos.bok.or.kr/api/ | Confirmed by ECOS metadata as `국고채(10년)`. |
| Korea 3s10s | `korea3s10s` | Derived from BOK ECOS | `817Y002:010210000-817Y002:010200000` | Derived | Daily | `bp` | https://ecos.bok.or.kr/api/ | Calculated only when KTB 10Y and 3Y inputs share the same verified date. |
| CD 91D (KOFR slot) | `kofr_cd91d` | BOK ECOS | `817Y002:010502000` | Direct | Daily | `%` | https://ecos.bok.or.kr/api/ | CD 91D is used in Phase 3A for the existing KOFR-or-CD dashboard slot. |
| EUR/USD | `eurusd` | Alpha Vantage | `FX_DAILY EUR/USD` | Direct | Daily | `USD` | https://www.alphavantage.co/documentation/ | Percentage changes use previous available observations. |
| USD/JPY | `usdjpy` | Alpha Vantage | `FX_DAILY USD/JPY` | Direct | Daily | `JPY` | https://www.alphavantage.co/documentation/ | Percentage changes use previous available observations. |
| USD/CNH | `usdcnh` | Alpha Vantage | `FX_DAILY USD/CNH` | Direct | Daily | `CNH` | https://www.alphavantage.co/documentation/ | Percentage changes use previous available observations. |
| USD/KRW | `usdkrw` | Alpha Vantage | `FX_DAILY USD/KRW` | Direct | Daily | `KRW` | https://www.alphavantage.co/documentation/ | Percentage changes use previous available observations. |
| S&P 500 | `spx` | Alpha Vantage | `INDEX_DATA SPX` | Direct | Daily | `index` | https://www.alphavantage.co/documentation/ | Accepted only if `INDEX_CATALOG` confirms an actual index symbol. |
| Nasdaq 100 | `ndx` | Alpha Vantage | `INDEX_DATA NDX` | Direct | Daily | `index` | https://www.alphavantage.co/documentation/ | Accepted only if `INDEX_CATALOG` confirms an actual index symbol. |
| BTC/USD | `btcusd` | CoinGecko | `bitcoin` market chart | Direct | Daily | `USD` | https://www.coingecko.com/en/coins/bitcoin | Uses CoinGecko market-chart observations. |
| ETH/USD | `ethusd` | CoinGecko | `ethereum` market chart | Direct | Daily | `USD` | https://www.coingecko.com/en/coins/ethereum | Uses CoinGecko market-chart observations. |
| Total crypto market cap | `total_crypto_mcap` | CoinGecko | `/global.total_market_cap.usd` | Direct | Intraday | `USD` | https://docs.coingecko.com/reference/crypto-global | Latest only in Phase 3A. |
| BTC dominance | `btc_dominance` | CoinGecko | `/global.market_cap_percentage.btc` | Direct | Intraday | `%` | https://docs.coingecko.com/reference/crypto-global | Latest only in Phase 3A. |
| DXY | `dxy` | Not enabled | `—` | `—` | Daily | `index` | `—` | Left as `—` until a reliable direct source is added. No synthetic DXY is calculated in Phase 3A. |
| KOSPI | `kospi` | Not enabled | `—` | `—` | Daily | `index` | `—` | Left as `—` until provider metadata confirms an actual index level. |
| KOSDAQ | `kosdaq` | Not enabled | `—` | `—` | Daily | `index` | `—` | Left as `—` until provider metadata confirms an actual index level. |
| MOVE | `move` | Not enabled | `—` | `—` | Daily | `index` | `—` | Left as `—`; no licensing workaround is implemented. |

## Change Methodology

`latest` is the latest verified provider observation, not the current calendar
date. Weekends and holidays are handled by using the most recent observation the
provider actually returns.

`1D` for daily series compares the latest verified observation with the
immediately previous available observation from the same provider response.

`1W` for daily market series compares the latest verified observation with the
configured lag in the provider registry. For most daily market series this is
approximately five trading observations. Crypto uses seven daily observations
because the market trades continuously.

Yield levels are stored in percentage points and yield changes are reported in
basis points. Price, FX, index, and crypto changes are percentage changes unless
the registry explicitly marks the series as point or percentage-point based.

Monthly or intraday latest-only mappings do not publish 1D/1W changes unless a
verified comparable history source is added later.

## Derived Spreads

Derived spreads are published only when all inputs are verified, numeric, and
from the same observation date. US 2s10s is `(DGS10 - DGS2) * 100`. Korea 3s10s
is `(KTB10Y - KTB3Y) * 100`. Both are stored in basis points and marked with
`derived: true` plus input provenance.

## History Upserts

`data/history.json` starts with empty series rather than placeholder points.
When a verified observation arrives:

1. A new date is appended.
2. The same date is replaced only by a verified numeric observation with valid provenance.
3. Existing verified history is never replaced by `null`, `—`, empty, malformed, or unverified values.
4. Points are stored in chronological order.
5. Duplicate dates are collapsed during upsert.

## Provider Priority

Lower numeric priority wins within the same update cycle:

| Priority | Provider | Scope |
| --- | --- | --- |
| 5 | Derived | Spreads calculated from verified official inputs |
| 10 | FRED | US rates, volatility proxy, public commodity series |
| 10 | BOK ECOS | Korea official rates and KTB/CD rate data |
| 20 | CoinGecko | Crypto market data |
| 30 | Alpha Vantage | FX and confirmed index data |

A lower-priority provider cannot overwrite a higher-priority verified
observation for the same instrument in the same run.

## Safety And Limitations

Provider adapters fail independently. A failed or rate-limited provider logs a
sanitized error, preserves existing verified values, and does not block other
providers.

Secrets are read only from environment variables and are never written into JSON
or logs. Source URLs must be absolute `http://` or `https://` URLs; relative,
`javascript:`, `data:`, `file:`, empty, or placeholder URLs are rejected.

FRED mappings are verified through official series metadata before observations
are accepted. BOK ECOS mappings are checked through official statistic item
metadata. Alpha Vantage index mappings are accepted only after `INDEX_CATALOG`
confirms the symbol. CoinGecko requires `COINGECKO_API_KEY`, uses the documented
public API base, and sends the key with the demo-key header; the pipeline does
not depend on undocumented unauthenticated behavior.

Known delays and caveats:

- FRED observations may lag by provider publishing schedule, especially around weekends and holidays.
- BOK ECOS daily series may follow Korea market/official publication calendars.
- Alpha Vantage free-tier and paid-tier limits can throttle FX/index updates.
- CoinGecko market data can be rate-limited by the account tier.
- DXY, KOSPI, KOSDAQ, MOVE, credit indices, ETF flows, CFTC positioning, and crypto derivatives remain placeholders until an approved verified provider is added.

## Official Documentation

- FRED API: https://fred.stlouisfed.org/docs/api/fred/
- BOK ECOS API: https://ecos.bok.or.kr/api/
- Alpha Vantage API: https://www.alphavantage.co/documentation/
- CoinGecko API: https://docs.coingecko.com/reference/introduction
