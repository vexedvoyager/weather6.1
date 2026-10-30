"""
v6.2 trading guards and scorecard settings (IMPROVEMENTS.md item #27).

Defaults live HERE so v6.2 works without touching config.yaml. To override any
of them, add a `guards:` section to config.yaml with the same key names.

Why each exists (all from the v6.1.1 analysis, 2026-10-29):
  min_yes_price_cents  - YES bets at 10c or less went 0 for 8 in v6.1.1 (-$42.77,
                         three-quarters of the whole loss) and 0 for 25 in v4. The
                         market prices those long shots right; the model did not.
  min_probability_gap  - the 10-20 point gap trades lost (-57% ROI); only gaps of
                         15+ points looked positive in a backtest on all markets.
  scorecard_exclude_cities - Seattle forecasts ran ~8F too low (7 of 7 actual highs
                         above the 90th percentile). Kept in shadow mode but left out
                         of the ALL-markets headline until the cause is found.
  checkpoint_city_days - the scorecard counts city-days (one ladder of brackets per
                         city per day). At this many, the stopping-rule line in the
                         Daily Summary says whether the model has beaten the market.
"""

GUARD_DEFAULTS = {
    "min_yes_price_cents": 11,          # never BUY YES at 10c or less (ask must be >= 11)
    "min_probability_gap": 0.15,        # model vs market must differ by at least 15 points
    "scorecard_exclude_cities": ["Seattle"],
    "checkpoint_city_days": 300,
}


def get_guards(cfg: dict) -> dict:
    """Defaults overlaid with any `guards:` section in config.yaml."""
    merged = dict(GUARD_DEFAULTS)
    merged.update((cfg or {}).get("guards") or {})
    return merged


def blocks_cheap_yes(side: str, price_cents: int, guards: dict) -> bool:
    """True if this would be a YES purchase below the minimum YES price."""
    return side.lower() == "yes" and price_cents < guards["min_yes_price_cents"]
