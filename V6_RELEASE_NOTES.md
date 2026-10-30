# Predict Weather Bot v6.2 — release notes

## v6.2 — guards from the first week of corrected data (2026-10-30)

Week-one analysis of v6.1.1 (32 settled trades, 522 scored markets): the corrected
forecasts are sound (median error +0.8F, typical miss 2.2F) but still lose to the
market on the all-markets scorecard (Brier 0.119 vs 0.102, Seattle excluded).
Most of the trading loss was one pattern: YES long shots at 10c or less (0 for 8,
-$42.77 of the -$57.03). v6.2 changes:

* **No YES purchases at 10c or less** (`guards.min_yes_price_cents`, default 11).
* **Minimum edge raised to 15 points** (`guards.min_probability_gap`; was 8).
* **Probability bounds widened to 1% / 99%** (were 5% / 95%). The 5% floor made
  the model say 8.5% for contracts that paid 1.3% of the time.
* **Seattle left out of the scorecard headline** (`guards.scorecard_exclude_cities`)
  because its forecasts ran ~8F too low. It still shows its own line, still shadow.
* **Scorecard now ignores wrong-column versions** (v4-v6.0) as well.
* **Stopping rule in the Daily Summary**: city-days scored vs 300, and whether the
  model is ahead of or behind the market (`guards.checkpoint_city_days`).
* **Dashboard**: open positions and recent settled trades now show the market day
  (the date the contract is about), when the position was opened and when it settled
  (all UTC).

All guard settings have defaults in code (src/guards.py); config.yaml does not need
to change. Add a `guards:` section there only to override them.


## v6.1.1 — bracket clamp fix (2026-10-22)

The 5%/95% clamp was applied to each END of a "between" bracket before
subtracting. In a tail bracket both ends hit the same bound, so the bracket
came out exactly 0.000 (Chicago 68-69F: real 3.3%, reported 0%), and brackets
near a tail were shrunk (17.3% became 12.5%). Now the bracket probability is
computed from the raw values and only the RESULT is clamped to [5%, 95%].
Nothing else changed. Trades opened under v6.1 keep that label; v6.1.1 is
scored separately.


## v6.1 — the model fix (2026-10-22)

The v6.0 column diagnostic, run on a real NOAA bulletin, found why the model
never beat the market. **From v4 through v6.0, every daily-high market was
forecast from NBM's overnight-MINIMUM column.**

* NBM's `TXN` rows alternate: the **12Z** columns are overnight minimums, the
  **00Z** columns are daytime maximums. (Chicago, run 2026-10-21T19Z: 12Z =
  52°F, 00Z = 70°F. Chicago's market ladder for that day was priced around
  70°F.)
* The bulletin separates cells with `|` after every 12Z column. The parser's
  character window picked up that `|`, so **every 00Z column read as blank**
  and the bot could only ever see the minimums. (It also dropped most columns
  at 100+ forecast hours.)
* Result: the model said "the high will be ~55°F" about days that reached
  ~87°F. It bought YES on every "less than" market (8% won) and NO on nearly
  every bracket. That is the YES-loses / NO-wins pattern seen since week one.

| Change | Where |
|---|---|
| Parser reads the real cell layout (4-character cells, `\|` separators, 3-digit hours) | `src/nbm.py` |
| Daily high comes from the **00Z column of the day after the market date**; never "nearest column" | `nbm.get_max_temp_forecast`, `forecast_refresh.py` |
| **Whole-degree settlement**: "greater than 75" = 76+, "less than 68" = 67−, "70–71" = 69.5 to 71.5. A full ladder of markets now sums to 1.0 (it summed to 0.44–0.68) | `forecast_refresh.model_probability_for_market` |
| Headline Brier scores **only the current version**; v4/v5/v6.0 are listed with a `*` as not a test of NBM | `daily_summary.py`, `generate_dashboard.py`, `version.py` |
| 8 shadow cities prefilled (Denver, Phoenix, Seattle, Atlanta, Dallas, Houston, Boston, Minneapolis) | `config.yaml` |
| Scorecard shows Brier with and without the 5%/95% clamp | `brier_tracker.py` |
| Regression tests built from the **real** bulletin | `tests/test_real_bulletin_v61.py`, `tests/fixtures/` |

Trading rules (edge thresholds, risk limits, the 5%/95% clamp, the
"≥24h to close" same-day floor) are **unchanged**. v6.1 is a clean restart of
the evidence: nothing before it measures how good NBM is.

## v6.0 — diagnose and instrument (2026-10-22)

Brier tracker fix (NO trades were scored on the wrong probability), market
price Brier benchmark, version stamps, forecast provenance, estimated fees,
market observations, shadow cities, series discovery, column diagnostic.

## Upgrading from v6.0

1. Upload the files in the v6.1 update zip (same folder structure), including
   the new `tests/fixtures/` folder. Do NOT upload any `data/trades.db`.
2. Actions → **Diagnose NBM Columns** → Run workflow. Section 5 now shows the
   NEW pick next to the OLD pick for every market; every NEW pick should read
   `[AFTERNOON/EVENING]` at a 00Z time.
3. Wait for the next **Forecast Refresh**. Its log should show markets cached
   for all cities (previously New York and Miami often showed none).

## What to expect

* The Daily Summary header reads `v6.1`; the Brier headline reads "no settled
  v6.1 trades yet" until the first v6.1 trades settle (about 2 days), and
  needs 30+ to be meaningful.
* "Model vs market, ALL markets observed" fills in as v6.1 markets settle —
  including the 8 shadow cities — and is the honest scorecard.
* Verdict gates are unchanged: no live mode until the corrected model has
  100+ settled trades, beats the base rate, and is not worse than the market.
