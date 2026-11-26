"""
Unit tests for live-incident entry price and portfolio margin guards:
1. Live price vs closed 30m SuperTrend inversion / narrow-stop guard (blocks open_long/open_short).
2. Per-trade margin / notional cap inside calculate_position_size.
3. Portfolio-wide total margin utilization cap (IMR protection) and remaining-budget scaling.
4. GateClient.get_account() initial_margin parsing.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest


def _make_ohlcv(n=60, start="2026-11-20", freq="30min", base=59000.0, step=-10.0):
    dates = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    closes = [base + i * step for i in range(n)]
    return pd.DataFrame({
        "open": [c + 5.0 for c in closes],
        "high": [c + 30.0 for c in closes],
        "low": [c - 30.0 for c in closes],
        "close": closes,
        "volume": [1000.0] * n,
    }, index=dates)


def _make_daily(n=200, end_date="2026-11-25", bullish=False):
    dates = pd.date_range(end=end_date, periods=n, freq="1D", tz="UTC")
    closes = [50000.0 + i * 50.0 for i in range(n)] if bullish else [70000.0 - i * 50.0 for i in range(n)]
    return pd.DataFrame({
        "open": closes,
        "high": [c + 100.0 for c in closes],
        "low": [c - 100.0 for c in closes],
        "close": closes,
        "volume": [5000.0] * n,
    }, index=dates)


def _build_strategy_for_test(monkeypatch, tmp_path, contract="BTC_USDT", account=None,
                             df_30m=None, st_30m_dir=-1, st_30m_val=59144.7,
                             bullish_macro=False, tick_size=0.1):
    import strategy
    import cooldown

    monkeypatch.setenv("STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(cooldown, "load_circuit_breaker_lock", lambda: {"locked": False})
    monkeypatch.setattr(strategy, "USE_ADX", False)
    monkeypatch.setattr(strategy, "MIN_SL_DISTANCE_PCT", 0.002)
    monkeypatch.setattr(strategy, "MAX_SINGLE_MARGIN_RATIO", 0.30)
    monkeypatch.setattr(strategy, "MAX_TOTAL_MARGIN_RATIO", 0.60)
    monkeypatch.setattr(strategy, "get_risk_amount", lambda equity, contract=None: {
        "amount": 16.69,
        "mode": "percent",
        "status": "normal",
        "weight": 0.35,
        "allocated_equity": equity * 0.35,
        "message": "test risk 16.69U",
    })

    if df_30m is None:
        df_30m = _make_ohlcv(n=60, freq="30min", base=59500.0, step=-10.0)
    df_1h = _make_ohlcv(n=60, freq="1h", base=59500.0, step=-15.0)
    df_4h = _make_ohlcv(n=60, freq="4h", base=59500.0, step=-30.0)
    df_1d = _make_daily(n=200, bullish=bullish_macro)

    st_30m = pd.DataFrame({
        "supertrend": [st_30m_val] * len(df_30m),
        "direction": [st_30m_dir] * len(df_30m),
    }, index=df_30m.index)
    st_1h = pd.DataFrame({
        "supertrend": [st_30m_val + (200.0 if st_30m_dir == -1 else -200.0)] * len(df_1h),
        "direction": [st_30m_dir] * len(df_1h),
    }, index=df_1h.index)

    client = MagicMock()
    client.get_account.return_value = account or {
        "total": 1161.0,
        "available": 1161.0,
        "initial_margin": 0.0,
        "unrealised_pnl": 0.0,
    }
    client.get_positions.return_value = None
    client.get_orders.return_value = []
    client.get_price_orders.return_value = []
    client.get_futures_contract.return_value = {"order_price_round": str(tick_size)}

    def _get_klines(c, interval, limit=100):
        if interval == "30m":
            return df_30m.copy()
        if interval == "1h":
            return df_1h.copy()
        if interval == "4h":
            return df_4h.copy()
        if interval == "1d":
            return df_1d.copy()
        return df_30m.copy()

    client.get_candlesticks.side_effect = _get_klines

    strat = strategy.TradingStrategy(client, contract=contract)
    return strat, st_30m, st_1h


def test_calculate_position_size_margin_cap():
    from strategy import calculate_position_size

    # Narrow SL on BTC: 16.69U risk / (18.3 * 0.0001) = 9120 contracts -> ~5395U margin without cap
    uncapped = calculate_position_size(
        risk_amount=16.69, entry_price=59163.0, stop_loss=59144.7, face_value=0.0001
    )
    assert uncapped["qty"] == 9120
    assert uncapped["capped"] is False

    # With 30% single-trade margin cap on 1161U equity (~348.3U margin -> 3483U notional)
    capped = calculate_position_size(
        risk_amount=16.69, entry_price=59163.0, stop_loss=59144.7,
        face_value=0.0001, max_margin=348.3
    )
    assert capped["capped"] is True
    assert capped["margin_required"] <= 348.3
    assert capped["qty"] == int((348.3 * 10) / (59163.0 * 0.0001))
    assert capped["qty"] < uncapped["qty"]


def test_short_entry_blocked_when_live_price_crosses_above_30m_st(monkeypatch, tmp_path):
    """Reproduces the live BTC incident: closed 30m ST is bearish at 59144.7, live price rebounded to 59163.0."""
    df_30m = _make_ohlcv(n=60, freq="30min", base=59500.0, step=-10.0)
    # Closed candle iloc[-2] is well below EMA20; live candle iloc[-1] rebounded above 59144.7
    df_30m.iloc[-2, df_30m.columns.get_loc("close")] = 58800.0
    df_30m.iloc[-1, df_30m.columns.get_loc("close")] = 59163.0

    strat, st_30m, st_1h = _build_strategy_for_test(
        monkeypatch, tmp_path, contract="BTC_USDT",
        df_30m=df_30m, st_30m_dir=-1, st_30m_val=59144.7, bullish_macro=False
    )

    with patch("strategy.calculate_supertrend", side_effect=[st_30m, st_1h]), \
         patch("indicators.calculate_chop", return_value=pd.Series([40.0] * 60)), \
         patch("indicators.calculate_kaufman_er", return_value=pd.Series([0.60] * 60)), \
         patch("indicators.calculate_atr_zscore", return_value=pd.Series([0.5] * 60)), \
         patch("cooldown.check_cooldown", return_value=MagicMock(triggered=False)):
        res = strat.analyze()

    assert res.action == "none"
    assert "防倒挂" in res.message


def test_short_entry_blocked_when_sl_distance_too_narrow(monkeypatch, tmp_path):
    """Live price is still below 30m ST, but gap (50 pts) < 0.2% (~118.2 pts)."""
    df_30m = _make_ohlcv(n=60, freq="30min", base=59500.0, step=-10.0)
    df_30m.iloc[-2, df_30m.columns.get_loc("close")] = 58800.0
    df_30m.iloc[-1, df_30m.columns.get_loc("close")] = 59100.0

    strat, st_30m, st_1h = _build_strategy_for_test(
        monkeypatch, tmp_path, contract="BTC_USDT",
        df_30m=df_30m, st_30m_dir=-1, st_30m_val=59150.0, bullish_macro=False
    )

    with patch("strategy.calculate_supertrend", side_effect=[st_30m, st_1h]), \
         patch("indicators.calculate_chop", return_value=pd.Series([40.0] * 60)), \
         patch("indicators.calculate_kaufman_er", return_value=pd.Series([0.60] * 60)), \
         patch("indicators.calculate_atr_zscore", return_value=pd.Series([0.5] * 60)), \
         patch("cooldown.check_cooldown", return_value=MagicMock(triggered=False)):
        res = strat.analyze()

    assert res.action == "none"


def test_long_entry_blocked_when_live_price_drops_below_30m_st(monkeypatch, tmp_path):
    df_30m = _make_ohlcv(n=60, freq="30min", base=1800.0, step=5.0)
    df_30m.iloc[-2, df_30m.columns.get_loc("close")] = 2200.0
    df_30m.iloc[-1, df_30m.columns.get_loc("close")] = 2040.0

    strat, st_30m, st_1h = _build_strategy_for_test(
        monkeypatch, tmp_path, contract="ETH_USDT",
        df_30m=df_30m, st_30m_dir=1, st_30m_val=2050.0, bullish_macro=True, tick_size=0.01
    )

    with patch("strategy.calculate_supertrend", side_effect=[st_30m, st_1h]), \
         patch("indicators.calculate_chop", return_value=pd.Series([40.0] * 60)), \
         patch("indicators.calculate_kaufman_er", return_value=pd.Series([0.60] * 60)), \
         patch("indicators.calculate_atr_zscore", return_value=pd.Series([0.5] * 60)), \
         patch("cooldown.check_cooldown", return_value=MagicMock(triggered=False)):
        res = strat.analyze()

    assert res.action == "none"


def test_portfolio_margin_cap_blocks_new_entry_when_imr_high(monkeypatch, tmp_path):
    """When portfolio initial_margin is already >= 60% of equity, block new entries to protect IMR."""
    df_30m = _make_ohlcv(n=60, freq="30min", base=59500.0, step=-10.0)
    df_30m.iloc[-2, df_30m.columns.get_loc("close")] = 58500.0
    df_30m.iloc[-1, df_30m.columns.get_loc("close")] = 58600.0

    high_margin_account = {
        "total": 1161.0,
        "available": 411.0,
        "initial_margin": 750.0,  # 64.6% > 60% cap
        "unrealised_pnl": -50.0,
    }
    strat, st_30m, st_1h = _build_strategy_for_test(
        monkeypatch, tmp_path, contract="BTC_USDT", account=high_margin_account,
        df_30m=df_30m, st_30m_dir=-1, st_30m_val=59144.7, bullish_macro=False
    )

    with patch("strategy.calculate_supertrend", side_effect=[st_30m, st_1h]), \
         patch("indicators.calculate_chop", return_value=pd.Series([40.0] * 60)), \
         patch("indicators.calculate_kaufman_er", return_value=pd.Series([0.60] * 60)), \
         patch("indicators.calculate_atr_zscore", return_value=pd.Series([0.5] * 60)), \
         patch("cooldown.check_cooldown", return_value=MagicMock(triggered=False)):
        res = strat.analyze()

    assert res.action == "none"
    assert res.details["portfolio_margin_blocked"] is True
    assert "IMR" in res.message


def test_portfolio_remaining_margin_scales_down_new_position(monkeypatch, tmp_path):
    """When used margin is 45% (450/1000), remaining budget is 150U (< 300U single cap); new entry caps at <= 150U."""
    df_30m = _make_ohlcv(n=60, freq="30min", base=59500.0, step=-10.0)
    df_30m.iloc[-2, df_30m.columns.get_loc("close")] = 58700.0
    df_30m.iloc[-1, df_30m.columns.get_loc("close")] = 58800.0

    partial_margin_account = {
        "total": 1000.0,
        "available": 550.0,
        "initial_margin": 450.0,  # 45% used, 150U remaining under 60% cap
        "unrealised_pnl": 0.0,
    }
    # SL distance = 59100 - 58800 = 300 -> uncapped qty = 16.69 / (300*0.0001) = 556 contracts -> margin 326.9U
    strat, st_30m, st_1h = _build_strategy_for_test(
        monkeypatch, tmp_path, contract="BTC_USDT", account=partial_margin_account,
        df_30m=df_30m, st_30m_dir=-1, st_30m_val=59100.0, bullish_macro=False
    )

    with patch("strategy.calculate_supertrend", side_effect=[st_30m, st_1h]), \
         patch("indicators.calculate_chop", return_value=pd.Series([40.0] * 60)), \
         patch("indicators.calculate_kaufman_er", return_value=pd.Series([0.60] * 60)), \
         patch("indicators.calculate_atr_zscore", return_value=pd.Series([0.5] * 60)), \
         patch("cooldown.check_cooldown", return_value=MagicMock(triggered=False)):
        res = strat.analyze()

    assert res.action == "open_short"
    assert res.details["margin_capped"] is True
    assert res.details["margin_required"] <= 150.0
    assert res.details["qty"] == int((150.0 * 10) / (58800.0 * 0.0001))


def test_gate_client_get_account_exposes_initial_margin():
    from gate_client import GateClient

    client = GateClient("k", "s")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "cross_margin_balance": "1161.0",
        "cross_available": "561.0",
        "cross_initial_margin": "550.0",
        "cross_order_margin": "50.0",
        "cross_unrealised_pnl": "-12.5",
    }
    client.session.get = MagicMock(return_value=mock_resp)

    acc = client.get_account()
    assert acc["total"] == pytest.approx(1161.0)
    assert acc["available"] == pytest.approx(561.0)
    assert acc["initial_margin"] == pytest.approx(600.0)
    assert acc["unrealised_pnl"] == pytest.approx(-12.5)
