"""v6.2 tests: cheap-YES guard, 15-point edge, scorecard exclusion + stopping rule, dashboard dates."""
import os
import tempfile
from unittest.mock import MagicMock, patch

from src import brier_tracker, db, guards
from src.generate_dashboard import generate_dashboard_html, _fmt_stamp, _fmt_market_day
from src.price_check import run_price_check


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    db.init_db(path)
    return path


# ---------------------------------------------------------------- guards module
def test_defaults_without_guards_section():
    g = guards.get_guards({})
    assert g["min_yes_price_cents"] == 11
    assert g["min_probability_gap"] == 0.15
    assert g["scorecard_exclude_cities"] == ["Seattle"]


def test_config_guards_section_overrides_defaults():
    g = guards.get_guards({"guards": {"min_probability_gap": 0.2}})
    assert g["min_probability_gap"] == 0.2
    assert g["min_yes_price_cents"] == 11  # untouched


def test_cheap_yes_blocked_but_cheap_no_and_normal_yes_allowed():
    g = guards.get_guards({})
    assert guards.blocks_cheap_yes("yes", 10, g)
    assert guards.blocks_cheap_yes("yes", 2, g)
    assert not guards.blocks_cheap_yes("yes", 11, g)
    assert not guards.blocks_cheap_yes("no", 2, g)


# ------------------------------------------------------------ price_check wiring
def _cfg(path):
    return {
        "mode": "paper", "paths": {"database": path},
        "risk": {"total_budget_usd": 50.0, "max_cost_per_trade_usd": 5.0,
                 "max_positions_per_city": 10, "daily_loss_limit_usd": 10.0},
        "operations": {"forecast_cache_max_age_hours": 8, "min_volume_contracts": 5},
        "edge": {"min_probability_gap": 0.05, "min_composite_score": 0.0,
                 "weights": {"spread": 0.3, "volume": 0.2, "imbalance": 0.25, "mispricing": 0.25}},
        "cities": [{"name": "Chicago", "kalshi_series_prefix": "KXHIGHCHI"}],
    }


def _run(path, ticker, model_prob, yes_bid, no_bid):
    db.upsert_forecast_cache(path, ticker, "Chicago", model_prob=model_prob, nbm_run_id="r")
    client = MagicMock()
    client.get_markets_by_series.return_value = [{
        "ticker": ticker, "yes_bid_dollars": yes_bid, "no_bid_dollars": no_bid,
        "volume_24h_fp": "100.00",
    }]
    client.get_orderbook.return_value = {"yes_dollars": [["0.10", "50.00"]], "no_dollars": [["0.10", "50.00"]]}
    client.get_positions.return_value = []
    with patch("src.price_check.build_client", return_value=client), \
         patch("src.price_check.run_settle_check",
               return_value={"checked": 0, "settled": 0, "still_open": 0, "unrecognized_result": 0}):
        run_price_check(_cfg(path))


def test_price_check_skips_yes_at_two_cents_despite_big_model_edge():
    path = _temp_db()
    # YES ask = 100 - no_bid(97) = 3c; model says 25% -> a big "edge" that lost 0 for 8 in v6.1.1.
    _run(path, "CHI-CHEAP", 0.25, "0.02", "0.97")
    assert db.count_open_trades(path) == 0


def test_price_check_still_buys_yes_at_normal_price():
    path = _temp_db()
    _run(path, "CHI-OK", 0.90, "0.15", "0.80")  # YES ask 20c
    assert db.count_open_trades(path) == 1


def test_price_check_requires_15_point_gap():
    path = _temp_db()
    # model 0.60 vs YES ask 0.50: gap 10 points -> below the 15-point minimum (old threshold was 8)
    _run(path, "CHI-SMALL", 0.60, "0.45", "0.50")
    assert db.count_open_trades(path) == 0
    # model 0.70 vs YES ask 0.50: gap 20 points -> trades
    _run(path, "CHI-BIG", 0.70, "0.45", "0.50")
    assert db.count_open_trades(path) == 1


# ------------------------------------------------------ scorecard + stopping rule
def _obs(path, ticker, city, model, yes_cents, outcome, version="v6.2", shadow=0):
    db.insert_market_observation(
        path, ticker=ticker, city=city, is_shadow_city=shadow, threshold_description="high 70-71°F",
        model_prob=model, raw_model_prob=model, market_yes_cents=yes_cents, market_yes_bid_cents=yes_cents - 1,
        volume_24h=10, nbm_run_id="r", nbm_forecast_hour=23, nbm_valid_utc="2026-10-23T00:00:00+00:00",
        ladder_json="{}", bot_version=version,
    )
    row = [r for r in db.get_pending_market_observations(path) if r["ticker"] == ticker][0]
    db.settle_market_observation(path, row["id"], outcome, "70.00")


def test_scorecard_excludes_cities_and_invalid_versions():
    path = _temp_db()
    _obs(path, "KXHIGHCHI-26OCT22-B70.5", "Chicago", 0.2, 20, "no")
    _obs(path, "KXHIGHTSEA-26OCT22-B70.5", "Seattle", 0.9, 5, "no", shadow=1)       # excluded city
    _obs(path, "KXHIGHCHI-26OCT22-B68.5", "Chicago", 0.9, 5, "no", version="v6.0")  # wrong column
    obs = brier_tracker.compute_observation_brier(path, exclude_cities=["Seattle"])
    assert obs["overall"]["n"] == 1                       # only the valid Chicago row
    assert obs["by_city"]["Seattle"]["excluded"] is True  # still shown, flagged
    assert obs["city_days"] == 1
    text = brier_tracker.format_observation_brier(obs)
    assert "EXCLUDED" in text and "STOPPING RULE: 1/300" in text


def test_stopping_rule_verdicts():
    base = {"overall": {"n": 5, "model_brier": 0.12, "market_brier": 0.10}, "by_city": {},
            "city_days": 300, "checkpoint_city_days": 300}
    assert "STILL BEHIND" in brier_tracker.format_observation_brier(base)
    ahead = dict(base, overall={"n": 5, "model_brier": 0.09, "market_brier": 0.10})
    assert "AHEAD of the market" in brier_tracker.format_observation_brier(ahead)
    early = dict(base, city_days=50)
    assert "50/300" in brier_tracker.format_observation_brier(early)


# ------------------------------------------------------------------ dashboard dates
def test_date_formatting_helpers():
    assert _fmt_stamp("2026-10-28T13:59:00+00:00") == "Oct 28, 13:59 UTC"
    assert _fmt_stamp(None) == "—"
    assert _fmt_market_day("KXHIGHCHI-26OCT28-B70.5") == "Oct 28"
    assert _fmt_market_day("garbage") == "—"


def test_dashboard_shows_market_day_opened_and_settled_dates():
    path = _temp_db()
    db.insert_trade(path, "KXHIGHCHI-26OCT28-B70.5", "Chicago", "no", 5, 60, 0.2, 0.8, "paper",
                    threshold_description="high 70-71°F")
    db.insert_trade(path, "KXHIGHMIA-26OCT27-B84.5", "Miami", "no", 5, 60, 0.2, 0.8, "paper",
                    threshold_description="high 84-85°F")
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute("UPDATE trades SET opened_at = '2026-10-27T13:59:00+00:00'")
    conn.execute("UPDATE trades SET status='settled', outcome='no', pnl_cents=100, "
                 "settled_at='2026-10-29T16:00:00+00:00' WHERE ticker LIKE '%MIA%'")
    conn.commit()
    conn.close()
    html = generate_dashboard_html(_cfg(path), path)
    assert "Market day" in html and "Opened" in html and "Settled" in html
    assert "Oct 28" in html and "Oct 27, 13:59 UTC" in html and "Oct 29, 16:00 UTC" in html


def test_config_guards_section_matches_code_defaults():
    from src.config import load_config
    cfg = load_config()
    assert cfg["guards"] == {k: guards.GUARD_DEFAULTS[k] for k in cfg["guards"]}
    assert set(cfg["guards"]) == set(guards.GUARD_DEFAULTS)
