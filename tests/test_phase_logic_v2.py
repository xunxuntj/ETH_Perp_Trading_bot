#!/usr/bin/env python3
"""
Production 3-stage trailing stop phase transition tests against TradingStrategy._infer_phase.
Replaces the legacy self-testing script with real assertions on production code.
"""

from unittest.mock import MagicMock
import pytest
import strategy
from strategy import TradingStrategy, Phase


def test_short_three_stage_phase_transitions(monkeypatch):
    """Verify SURVIVAL -> LOCKED (at 1.0R) -> HOURLY (1H ST < lock_price) for short positions."""
    monkeypatch.setattr(strategy, "LOCK_PROFIT_BUFFER", 0.5)
    strat = TradingStrategy(MagicMock(), contract="ETH_USDT")

    # entry=2060, initial_30m_st=2080 -> 1R = 20, lock_price = 2060 - 0.5*20 = 2050
    # 1. Floating profit 0.5R (curr=2050 < 1.0R) -> stays SURVIVAL, trails 30m ST
    phase, sl = strat._infer_phase(
        entry_price=2060.0, current_price=2050.0, qty=10,
        last_30m_st=2075.0, last_1h_st=2085.0, is_long=False,
        initial_30m_st=2080.0, prev_stop_loss=2080.0, prev_phase="survival"
    )
    assert phase == Phase.SURVIVAL.value
    assert sl == pytest.approx(2075.0)

    # 2. Floating profit hits 1.0R (curr=2040) -> unlocks LOCKED, stop forced to 2050 (entry - 0.5R)
    phase, sl = strat._infer_phase(
        entry_price=2060.0, current_price=2040.0, qty=10,
        last_30m_st=2065.0, last_1h_st=2060.0, is_long=False,
        initial_30m_st=2080.0, prev_stop_loss=2075.0, prev_phase="survival"
    )
    assert phase == Phase.LOCKED.value
    assert sl == pytest.approx(2050.0)

    # 3. 1H ST crosses below lock_price (2045 < 2050) -> switches to HOURLY
    phase, sl = strat._infer_phase(
        entry_price=2060.0, current_price=2025.0, qty=10,
        last_30m_st=2040.0, last_1h_st=2045.0, is_long=False,
        initial_30m_st=2080.0, prev_stop_loss=2050.0, prev_phase="locked"
    )
    assert phase == Phase.HOURLY.value
    assert sl == pytest.approx(2045.0)

    # 4. Tighten-only in HOURLY: 1H ST rebounds to 2048 -> stop must stay at 2045
    phase, sl = strat._infer_phase(
        entry_price=2060.0, current_price=2030.0, qty=10,
        last_30m_st=2040.0, last_1h_st=2048.0, is_long=False,
        initial_30m_st=2080.0, prev_stop_loss=2045.0, prev_phase="hourly"
    )
    assert phase == Phase.HOURLY.value
    assert sl == pytest.approx(2045.0)
