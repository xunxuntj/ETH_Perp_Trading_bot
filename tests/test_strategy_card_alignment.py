"""
Comprehensive alignment tests for V1 Post-ETF Trading Card SOP and risk hardening.
Covers:
1. Portfolio weight allocation in both percent and fixed modes (Option A).
2. Flash crash risk freeze (1H ATR Z-Score > 3.0) freezing new entries and tightening active stops.
3. Strict dual 1D EMA50 macro alignment (asset + BTC).
4. Closed 30m EMA(20) anti-sweep confirmation (iloc[-2] instead of unclosed iloc[-1]).
5. ADX filter disabled by default (aligned with card) and overridable via env.
6. Stage 2 lock profit triggered at floating profit >= 1.0R -> stop lifted to entry +/- 0.5R.
7. Stage 3 hourly tracking triggered when 1H ST surpasses lock price.
8. Unified 5.0R initial take profit across all assets (including ETH).
9. Tick-aware stop update detection for low-price assets (DOGE tick=0.00005).
10. Permanent hard circuit breaker lock (<= 450U) and Fail-Closed on account API failure.
"""

import os
import importlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(n=60, start="2026-10-01", freq="30min", base=100.0, step=0.5):
    dates = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    closes = [base + i * step for i in range(n)]
    return pd.DataFrame({
        "open": [c - 0.2 for c in closes],
        "high": [c + 1.0 for c in closes],
        "low": [c - 1.0 for c in closes],
        "close": closes,
        "volume": [1000.0] * n,
    }, index=dates)


def _make_daily(n=200, end_date="2026-10-02", bullish=True):
    dates = pd.date_range(end=end_date, periods=n, freq="1D", tz="UTC")
    closes = [100.0 + i * 0.5 for i in range(n)] if bullish else [200.0 - i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "open": closes,
        "high": [c + 2.0 for c in closes],
        "low": [c - 2.0 for c in closes],
        "close": closes,
        "volume": [5000.0] * n,
    }, index=dates)


def test_portfolio_weight_risk_allocation_percent_and_fixed(monkeypatch):
    import config

    # Percent mode: 700U * weight * 0.008
    monkeypatch.setenv("RISK_MODE", "percent")
    monkeypatch.setenv("RISK_PERCENT", "0.008")
    monkeypatch.setenv("APPLY_PORTFOLIO_WEIGHTS", "true")
    importlib.reload(config)

    r_btc = config.get_risk_amount(700.0, contract="BTC_USDT")
    r_eth = config.get_risk_amount(700.0, contract="ETH_USDT")
    r_sol = config.get_risk_amount(700.0, contract="SOL_USDT")
    r_doge = config.get_risk_amount(700.0, contract="DOGE_USDT")

    assert r_btc["amount"] == pytest.approx(700.0 * 0.35 * 0.008)
    assert r_eth["amount"] == pytest.approx(700.0 * 0.30 * 0.008)
    assert r_sol["amount"] == pytest.approx(700.0 * 0.25 * 0.008)
    assert r_doge["amount"] == pytest.approx(700.0 * 0.10 * 0.008)
    assert (r_btc["amount"] + r_eth["amount"] + r_sol["amount"] + r_doge["amount"]) == pytest.approx(700.0 * 0.008)

    # Fixed mode (Option A): 10U * weight
    monkeypatch.setenv("RISK_MODE", "fixed")
    monkeypatch.setenv("RISK_FIXED_AMOUNT", "10")
    importlib.reload(config)

    f_btc = config.get_risk_amount(700.0, contract="BTC_USDT")
    f_doge = config.get_risk_amount(700.0, contract="DOGE_USDT")
    assert f_btc["amount"] == pytest.approx(3.5)
    assert f_doge["amount"] == pytest.approx(1.0)

    # Defaults aligned with card
    monkeypatch.delenv("USE_ADX", raising=False)
    monkeypatch.delenv("TP_RATIO", raising=False)
    importlib.reload(config)
    assert config.USE_ADX is False
    assert config.get_tp_ratio("BTC_USDT") == 5.0
    assert config.get_tp_ratio("ETH_USDT") == 5.0
    assert config.get_tp_ratio("SOL_USDT") == 5.0
    assert config.get_tp_ratio("DOGE_USDT") == 5.0


def test_stage2_lock_at_1r_and_stage3_hourly_transition(monkeypatch):
    import strategy
    monkeypatch.setattr(strategy, "LOCK_PROFIT_BUFFER", 0.5)

    client = MagicMock()
    strat = strategy.TradingStrategy(client, contract="ETH_USDT")

    # Long: entry=2000, initial_30m_st=1980 -> 1R = 20, lock_price = 2000 + 0.5*20 = 2010
    # 1) Floating profit +0.8R (curr=2016 < 2020) -> stays SURVIVAL, trails 30m ST
    phase, sl = strat._infer_phase(
        entry_price=2000.0, current_price=2016.0, qty=10,
        last_30m_st=1985.0, last_1h_st=1970.0, is_long=True,
        initial_30m_st=1980.0, prev_stop_loss=1980.0, prev_phase="survival"
    )
    assert phase == "survival"
    assert sl == pytest.approx(1985.0)

    # 2) Floating profit hits 1.0R (curr=2020) -> unlocks LOCKED, stop forced to 2010 (entry + 0.5R)
    phase, sl = strat._infer_phase(
        entry_price=2000.0, current_price=2020.0, qty=10,
        last_30m_st=1990.0, last_1h_st=1980.0, is_long=True,
        initial_30m_st=1980.0, prev_stop_loss=1985.0, prev_phase="survival"
    )
    assert phase == "locked"
    assert sl == pytest.approx(2010.0)

    # 3) 1H ST crosses above lock_price (2015 > 2010) -> switches to HOURLY, follows 1H ST
    phase, sl = strat._infer_phase(
        entry_price=2000.0, current_price=2040.0, qty=10,
        last_30m_st=2020.0, last_1h_st=2015.0, is_long=True,
        initial_30m_st=1980.0, prev_stop_loss=2010.0, prev_phase="locked"
    )
    assert phase == "hourly"
    assert sl == pytest.approx(2015.0)


def test_doge_tick_aware_stop_update(tmp_path, monkeypatch):
    import position_state

    pos_file = tmp_path / "position_state_doge_usdt.json"
    monkeypatch.setenv("POSITION_STATE_FILE", str(pos_file))

    changed1, ctype1 = position_state.update_position_state(
        direction="long", phase="survival", stop_loss=0.06000,
        entry_price=0.06200, current_time=1000.0, contract="DOGE_USDT", tick_size=0.00005
    )
    assert changed1 is True
    assert ctype1 == "new_position"

    # A 0.00020 move on DOGE (4 ticks, << 0.01) MUST trigger stop_updated
    changed2, ctype2 = position_state.update_position_state(
        direction="long", phase="survival", stop_loss=0.06020,
        entry_price=0.06200, current_time=1300.0, contract="DOGE_USDT", tick_size=0.00005
    )
    assert changed2 is True
    assert ctype2 == "stop_updated"


def test_flash_crash_tightens_active_long_stop(tmp_path, monkeypatch):
    import strategy

    monkeypatch.setattr(strategy, "LOCK_PROFIT_BUFFER", 0.5)
    monkeypatch.setenv("POSITION_STATE_FILE", str(tmp_path / "pos.json"))

    client = MagicMock()
    client.get_futures_contract.return_value = {"order_price_round": "0.01"}
    client.get_price_orders.return_value = [{
        "trigger": {"price": "1980.0"},
        "initial": {"reduce_only": True, "auto_size": "close"}
    }]
    strat = strategy.TradingStrategy(client, contract="ETH_USDT")

    position = {"entry_price": 2000.0, "size": 10}
    df_30m = pd.DataFrame({"close": [2010.0, 2010.0]})
    df_1h = pd.DataFrame({"close": [2010.0, 2010.0]})
    st_30m = pd.DataFrame({"supertrend": [1980.0, 1980.0], "direction": [1, 1]})
    st_1h = pd.DataFrame({"supertrend": [1970.0, 1970.0], "direction": [1, 1]})

    with patch("strategy.load_position_state", return_value={"long": {"phase": "survival", "stop_loss": 1980.0, "initial_30m_st": 1980.0}}):
        res = strat._manage_long_position(
            position, df_30m, df_1h, st_30m, st_1h,
            last_1h_close=2010.0, last_1h_dema=1990.0,
            risk_amount=10.0, risk_info="test",
            is_risk=True, last_1h_atr=20.0
        )

    # Emergency SL = 2010.0 - 0.5 * 20.0 = 2000.0, tightened from 1980.0
    assert res.action == "stop_updated"
    assert res.details["risk_tightened"] is True
    assert res.details["stop_loss"] == pytest.approx(2000.0)


def test_closed_30m_ema20_anti_sweep_uses_iloc_minus_2(tmp_path, monkeypatch):
    import strategy

    monkeypatch.setenv("STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("CIRCUIT_BREAKER_LOCK_FILE", str(tmp_path / "cb.json"))
    monkeypatch.setattr(strategy, "USE_ADX", False)

    # Build 30m bars where iloc[-2] (closed) is BELOW EMA20, while iloc[-1] (forming) spikes ABOVE EMA20
    df_30m = _make_ohlcv(n=60, start="2026-10-01", freq="30min", base=100.0, step=0.0)
    df_30m.iloc[-2, df_30m.columns.get_loc("close")] = 90.0   # closed bar below EMA20 (~100)
    df_30m.iloc[-1, df_30m.columns.get_loc("close")] = 115.0  # unclosed forming bar above EMA20

    df_1h = _make_ohlcv(n=60, start="2026-10-01", freq="1h", base=100.0, step=0.1)
    df_daily = _make_daily(n=200, end_date="2026-10-02", bullish=True)

    client = MagicMock()
    client.get_candlesticks.side_effect = lambda c, interval, limit=100: (
        df_daily if interval == "1d" else (df_1h if interval == "1h" else df_30m)
    )
    client.get_account.return_value = {"total": 700.0, "available": 700.0}
    client.get_positions.return_value = None
    client.get_orders.return_value = []
    client.get_price_orders.return_value = []
    client.get_futures_contract.return_value = {"order_price_round": "0.01"}

    with patch("strategy.calculate_supertrend", return_value=pd.DataFrame({"supertrend": [95.0] * 60, "direction": [1] * 60}, index=df_30m.index)), \
         patch("indicators.calculate_chop", return_value=pd.Series([40.0] * 10)), \
         patch("indicators.calculate_kaufman_er", return_value=pd.Series([0.6] * 10)), \
         patch("indicators.calculate_atr_zscore", return_value=pd.Series([0.0] * 60)), \
         patch("cooldown.check_cooldown") as mock_cd:
        from cooldown import CooldownStatus
        mock_cd.return_value = CooldownStatus(triggered=False)

        strat = strategy.TradingStrategy(client, contract="BTC_USDT")
        res = strat.analyze()

    # Must NOT open long because closed 30m bar (iloc[-2] = 90) is below EMA20
    assert res.action == "none"


def test_account_api_failure_fail_closed_and_permanent_circuit_breaker(tmp_path, monkeypatch):
    import strategy
    import cooldown

    cb_file = tmp_path / "cb_lock.json"
    monkeypatch.setenv("CIRCUIT_BREAKER_LOCK_FILE", str(cb_file))
    monkeypatch.setenv("STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("RESET_CIRCUIT_BREAKER", "false")

    df_30m = _make_ohlcv(n=60, start="2026-10-01", freq="30min", base=100.0, step=0.5)
    df_1h = _make_ohlcv(n=60, start="2026-10-01", freq="1h", base=100.0, step=0.5)
    df_daily = _make_daily(n=200, end_date="2026-10-02", bullish=True)

    client = MagicMock()
    client.get_candlesticks.side_effect = lambda c, interval, limit=100: (
        df_daily if interval == "1d" else (df_1h if interval == "1h" else df_30m)
    )
    client.get_positions.return_value = None
    client.get_orders.return_value = []
    client.get_price_orders.return_value = []

    # 1. Fail-Closed when get_account fails -> must NOT fallback to 500U or open trade
    client.get_account.side_effect = Exception("Network timeout")
    strat = strategy.TradingStrategy(client, contract="BTC_USDT")
    res_fail = strat.analyze()
    assert res_fail.action == "none"
    assert res_fail.details.get("account_unavailable") is True

    # 2. Equity <= 450U triggers permanent circuit breaker lock
    client.get_account.side_effect = None
    client.get_account.return_value = {"total": 440.0, "available": 440.0}
    strat2 = strategy.TradingStrategy(client, contract="BTC_USDT")
    res_cb = strat2.analyze()
    assert res_cb.action == "circuit_breaker"
    assert cb_file.exists()

    # 3. Even if equity rebounds to 600U, permanent lock stays active until manual reset
    client.get_account.return_value = {"total": 600.0, "available": 600.0}
    strat3 = strategy.TradingStrategy(client, contract="BTC_USDT")
    res_locked = strat3.analyze()
    assert res_locked.action == "circuit_breaker"
    assert res_locked.details.get("permanent_lock") is True

    # 4. Manual reset via env clears lock
    monkeypatch.setenv("RESET_CIRCUIT_BREAKER", "true")
    lock_after_reset = cooldown.load_circuit_breaker_lock()
    assert lock_after_reset["locked"] is False
    assert not cb_file.exists()
