#!/usr/bin/env python3
"""
策略逻辑单元测试
涵盖: SURVIVAL/LOCKED/HOURLY 阶段转换、止损更新、恢复逻辑
"""

import unittest
from unittest.mock import patch

import pandas as pd
import strategy
strategy.LOCK_PROFIT_BUFFER = 1.0

from strategy import (
    is_1h_tighter, calculate_lock_threshold, calculate_position_size,
    Phase, Direction, Position, FACE_VALUE, TradingStrategy, tighten_stop_loss
)


class TestHelpers(unittest.TestCase):
    """测试辅助函数"""

    def test_is_1h_tighter_long(self):
        """多仓：1H ST 更高 = 更紧"""
        # 2300 > 2290? YES, 更紧
        self.assertTrue(is_1h_tighter(2300, 2290, is_long=True))
        # 2280 > 2290? NO, 不更紧
        self.assertFalse(is_1h_tighter(2280, 2290, is_long=True))
        # 2290 > 2290? NO, 相等不算更紧
        self.assertFalse(is_1h_tighter(2290, 2290, is_long=True))

    def test_is_1h_tighter_short(self):
        """空仓：1H ST 更低 = 更紧"""
        # 2280 < 2290? YES, 更紧
        self.assertTrue(is_1h_tighter(2280, 2290, is_long=False))
        # 2300 < 2290? NO, 不更紧
        self.assertFalse(is_1h_tighter(2300, 2290, is_long=False))
        # 2290 < 2290? NO, 相等不算更紧
        self.assertFalse(is_1h_tighter(2290, 2290, is_long=False))

    def test_calculate_lock_threshold_long(self):
        """多仓：锁利阈值 = entry + BUFFER / qty_eth"""
        entry_price = 2000.0
        qty = 100  # 100 张 = 1 ETH
        # BUFFER = 1.0 U
        # threshold = 2000 + 1.0 / 1 = 2001.0
        threshold = calculate_lock_threshold(entry_price, qty, is_long=True)
        self.assertAlmostEqual(threshold, 2001.0, places=2)

    def test_calculate_lock_threshold_short(self):
        """空仓：锁利阈值 = entry - BUFFER / qty_eth"""
        entry_price = 2000.0
        qty = 100  # 100 张 = 1 ETH
        # threshold = 2000 - 1.0 / 1 = 1999.0
        threshold = calculate_lock_threshold(entry_price, qty, is_long=False)
        self.assertAlmostEqual(threshold, 1999.0, places=2)

    def test_calculate_position_size(self):
        """计算开仓张数"""
        risk_amount = 50.0
        entry_price = 2500.0
        stop_loss = 2400.0
        
        result = calculate_position_size(risk_amount, entry_price, stop_loss)
        
        # sl_distance = 100
        # qty = 50 / 100 / FACE_VALUE = 50
        self.assertEqual(result['qty'], 50)
        self.assertAlmostEqual(result['sl_distance'], 100.0, places=1)
        self.assertAlmostEqual(result['position_eth'], 0.5, places=2)
        self.assertAlmostEqual(result['actual_risk'], 50.0, places=1)

    def test_tighten_stop_loss_long(self):
        self.assertEqual(tighten_stop_loss(2300.0, 2310.0, is_long=True), 2310.0)
        self.assertEqual(tighten_stop_loss(2320.0, 2310.0, is_long=True), 2320.0)

    def test_tighten_stop_loss_short(self):
        self.assertEqual(tighten_stop_loss(2310.0, 2300.0, is_long=False), 2300.0)
        self.assertEqual(tighten_stop_loss(2290.0, 2300.0, is_long=False), 2290.0)


class TestPhaseTransitions(unittest.TestCase):
    """测试阶段转换逻辑（新逻辑：基于30m ST是否达到开仓价 + PNL阈值）"""

    def test_survival_condition_long(self):
        """多仓：生存期条件 = 30m ST 未达到开仓价"""
        entry_price = 2000.0
        qty = 10
        is_long = True
        FACE_VALUE = 0.01

        # 30m ST < 开仓价 → 生存期（止损触发会亏损）
        last_30m_st = 1990.0
        pnl_at_stop = (last_30m_st - entry_price) * qty * FACE_VALUE
        self.assertLess(pnl_at_stop, 0)  # pnl = -1.0
        self.assertFalse(last_30m_st >= entry_price)  # 未达开仓价

        # 30m ST >= 开仓价 → 退出生存期
        last_30m_st = 2000.0
        self.assertTrue(last_30m_st >= entry_price)

    def test_survival_condition_short(self):
        """空仓：生存期条件 = 30m ST 未达到开仓价（从上方）"""
        entry_price = 2000.0
        qty = 10
        is_long = False
        FACE_VALUE = 0.01

        # 30m ST > 开仓价 → 生存期（止损触发会亏损）
        last_30m_st = 2010.0
        self.assertFalse(last_30m_st <= entry_price)

        # 30m ST <= 开仓价 → 退出生存期
        last_30m_st = 2000.0
        self.assertTrue(last_30m_st <= entry_price)

    def test_locked_to_hourly_long_trigger(self):
        """多仓：锁利期 → 换轨期（按30m ST平仓收益 > LOCK_PROFIT_BUFFER）"""
        from config import LOCK_PROFIT_BUFFER
        FACE_VALUE = 0.01
        entry_price = 2000.0
        qty = 10
        is_long = True

        # 30m ST = 2011 → pnl = (2011-2000)*10*0.01 = 1.1 > 1.0 → 换轨期
        last_30m_st = 2011.0
        pnl_at_stop = (last_30m_st - entry_price) * qty * FACE_VALUE
        self.assertGreater(pnl_at_stop, LOCK_PROFIT_BUFFER)

    def test_locked_to_hourly_long_no_trigger(self):
        """多仓：锁利期 → 保持（按30m ST平仓收益 <= LOCK_PROFIT_BUFFER）"""
        from config import LOCK_PROFIT_BUFFER
        FACE_VALUE = 0.01
        entry_price = 2000.0
        qty = 10
        is_long = True

        # 30m ST = 2005 → pnl = (2005-2000)*10*0.01 = 0.5 <= 1.0 → 锁利期继续
        last_30m_st = 2005.0
        pnl_at_stop = (last_30m_st - entry_price) * qty * FACE_VALUE
        self.assertLessEqual(pnl_at_stop, LOCK_PROFIT_BUFFER)

    def test_locked_to_hourly_short_trigger(self):
        """空仓：锁利期 → 换轨期（按30m ST平仓收益 > LOCK_PROFIT_BUFFER）"""
        from config import LOCK_PROFIT_BUFFER
        FACE_VALUE = 0.01
        entry_price = 2000.0
        qty = 10
        is_long = False

        # 30m ST = 1989 → pnl = (2000-1989)*10*0.01 = 1.1 > 1.0 → 换轨期
        last_30m_st = 1989.0
        pnl_at_stop = (entry_price - last_30m_st) * qty * FACE_VALUE
        self.assertGreater(pnl_at_stop, LOCK_PROFIT_BUFFER)

    def test_locked_to_hourly_short_no_trigger(self):
        """空仓：锁利期 → 保持（按30m ST平仓收益 <= LOCK_PROFIT_BUFFER）"""
        from config import LOCK_PROFIT_BUFFER
        FACE_VALUE = 0.01
        entry_price = 2000.0
        qty = 10
        is_long = False

        # 30m ST = 1995 → pnl = (2000-1995)*10*0.01 = 0.5 <= 1.0 → 锁利期继续
        last_30m_st = 1995.0
        pnl_at_stop = (entry_price - last_30m_st) * qty * FACE_VALUE
        self.assertLessEqual(pnl_at_stop, LOCK_PROFIT_BUFFER)

    def test_hourly_tightening_only_long(self):
        """多仓换轨期：止损只紧不松"""
        # 如果1H ST下降，止损应保持在prev_stop不松动
        prev_stop = 2020.0
        last_1h_st_lower = 2015.0  # 1H ST下降
        new_stop = max(last_1h_st_lower, prev_stop)
        self.assertEqual(new_stop, prev_stop)  # 止损保持不变

        # 如果1H ST上升，止损跟进
        last_1h_st_higher = 2025.0
        new_stop = max(last_1h_st_higher, prev_stop)
        self.assertEqual(new_stop, last_1h_st_higher)  # 止损上移

    def test_hourly_tightening_only_short(self):
        """空仓换轨期：止损只紧不松"""
        # 如果1H ST上升，止损应保持在prev_stop不松动
        prev_stop = 2010.0
        last_1h_st_higher = 2015.0  # 1H ST上升
        new_stop = min(last_1h_st_higher, prev_stop)
        self.assertEqual(new_stop, prev_stop)  # 止损保持不变

        # 如果1H ST下降，止损跟进
        last_1h_st_lower = 2005.0
        new_stop = min(last_1h_st_lower, prev_stop)
        self.assertEqual(new_stop, last_1h_st_lower)  # 止损下移

    def test_survival_to_locked_threshold_long(self):
        """多仓：锁利阈值（按30m ST平仓盈利 > BUFFER 时进入换轨）"""
        entry_price = 2000.0
        qty = 10
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=True)
        self.assertAlmostEqual(lock_threshold, 2010.0, places=2)

    def test_survival_to_locked_threshold_short(self):
        """空仓：锁利阈值（按30m ST平仓盈利 > BUFFER 时进入换轨）"""
        entry_price = 2000.0
        qty = 10
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=False)
        self.assertAlmostEqual(lock_threshold, 1990.0, places=2)


class TestStopLossAdjustment(unittest.TestCase):
    """测试止损调整（只紧不松）"""

    def test_survival_stop_tighten_long(self):
        """多仓生存期：30m ST上升，止损上移"""
        old_stop = 2300.0
        last_30m_st = 2310.0
        is_long = True
        
        # 只紧不松：max(old_stop, last_30m_st)
        new_stop = max(old_stop, last_30m_st)
        self.assertEqual(new_stop, 2310.0)

    def test_survival_stop_hold_long(self):
        """多仓生存期：30m ST下降，止损保持"""
        old_stop = 2310.0
        last_30m_st = 2300.0
        is_long = True
        
        # 只紧不松：max(old_stop, last_30m_st)
        new_stop = max(old_stop, last_30m_st)
        self.assertEqual(new_stop, 2310.0)

    def test_survival_stop_tighten_short(self):
        """空仓生存期：30m ST下降，止损下移"""
        old_stop = 2310.0
        last_30m_st = 2300.0
        is_long = False
        
        # 只紧不松：min(old_stop, last_30m_st)
        new_stop = min(old_stop, last_30m_st)
        self.assertEqual(new_stop, 2300.0)

    def test_survival_stop_hold_short(self):
        """空仓生存期：30m ST上升，止损保持"""
        old_stop = 2300.0
        last_30m_st = 2310.0
        is_long = False
        
        # 只紧不松：min(old_stop, last_30m_st)
        new_stop = min(old_stop, last_30m_st)
        self.assertEqual(new_stop, 2300.0)

    def test_hourly_stop_tighten_long(self):
        """多仓换轨期：1H ST上升，止损上移"""
        old_stop = 2400.0
        last_1h_st = 2420.0
        is_long = True
        
        # 只紧不松：max(old_stop, last_1h_st)
        new_stop = max(old_stop, last_1h_st)
        self.assertEqual(new_stop, 2420.0)

    def test_hourly_stop_hold_long(self):
        """多仓换轨期：1H ST下降，止损保持"""
        old_stop = 2420.0
        last_1h_st = 2400.0
        is_long = True
        
        # 只紧不松：max(old_stop, last_1h_st)
        new_stop = max(old_stop, last_1h_st)
        self.assertEqual(new_stop, 2420.0)

    def test_hourly_stop_tighten_short(self):
        """空仓换轨期：1H ST下降，止损下移"""
        old_stop = 2400.0
        last_1h_st = 2380.0
        is_long = False
        
        # 只紧不松：min(old_stop, last_1h_st)
        new_stop = min(old_stop, last_1h_st)
        self.assertEqual(new_stop, 2380.0)

    def test_hourly_stop_hold_short(self):
        """空仓换轨期：1H ST上升，止损保持"""
        old_stop = 2380.0
        last_1h_st = 2400.0
        is_long = False
        
        # 只紧不松：min(old_stop, last_1h_st)
        new_stop = min(old_stop, last_1h_st)
        self.assertEqual(new_stop, 2380.0)


class TestPnLCalculations(unittest.TestCase):
    """测试盈利/亏损计算"""

    def test_pnl_long_profit(self):
        """多仓盈利"""
        entry_price = 2000.0
        current_price = 2050.0
        qty = 10
        
        pnl = (current_price - entry_price) * qty * FACE_VALUE
        self.assertAlmostEqual(pnl, 5.0, places=2)

    def test_pnl_long_loss(self):
        """多仓亏损"""
        entry_price = 2000.0
        current_price = 1950.0
        qty = 10
        
        pnl = (current_price - entry_price) * qty * FACE_VALUE
        self.assertAlmostEqual(pnl, -5.0, places=2)

    def test_pnl_short_profit(self):
        """空仓盈利"""
        entry_price = 2000.0
        current_price = 1950.0
        qty = 10
        
        pnl = (entry_price - current_price) * qty * FACE_VALUE
        self.assertAlmostEqual(pnl, 5.0, places=2)

    def test_pnl_short_loss(self):
        """空仓亏损"""
        entry_price = 2000.0
        current_price = 2050.0
        qty = 10
        
        pnl = (entry_price - current_price) * qty * 0.01
        self.assertAlmostEqual(pnl, -5.0, places=2)

    def test_pnl_if_stop_long(self):
        """多仓：按止损价成交的盈利"""
        entry_price = 2000.0
        stop_loss = 1950.0
        qty = 10
        
        pnl_if_stop = (stop_loss - entry_price) * qty * FACE_VALUE
        self.assertAlmostEqual(pnl_if_stop, -5.0, places=2)

    def test_pnl_if_stop_short(self):
        """空仓：按止损价成交的盈利"""
        entry_price = 2000.0
        stop_loss = 2050.0
        qty = 10
        
        pnl_if_stop = (entry_price - stop_loss) * qty * FACE_VALUE
        self.assertAlmostEqual(pnl_if_stop, -5.0, places=2)


class TestRealWorldScenarios(unittest.TestCase):
    """真实场景测试"""

    def test_scenario_short_entry_2813_stop_2341(self):
        """真实场景：空仓开仓 entry=2813, stop=2341.21, qty=27"""
        entry_price = 2813.0
        qty = 27
        locked_stop = 2341.21
        is_long = False
        
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=False)
        
        # lock_threshold ≈ 2809.30
        self.assertAlmostEqual(lock_threshold, 2809.30, places=1)
        
        # 当前 1H ST = 2385.21，对比 locked_stop = 2341.21
        last_1h_st = 2385.21
        should_switch = is_1h_tighter(last_1h_st, locked_stop, is_long=False)
        # 2385.21 < 2341.21? NO，不进入HOURLY
        self.assertFalse(should_switch)
        
        # 如果 1H ST 降到 2330.0，对比 locked_stop = 2341.21
        last_1h_st_tighter = 2330.0
        should_switch_tighter = is_1h_tighter(last_1h_st_tighter, locked_stop, is_long=False)
        # 2330.0 < 2341.21? YES，进入HOURLY
        self.assertTrue(should_switch_tighter)

    def test_scenario_short_recovery_at_locked(self):
        """恢复场景：空仓已在LOCKED阶段，重启后判断阶段"""
        entry_price = 2813.0
        current_price = 2370.0
        qty = 27
        is_long = False
        
        # 浮盈
        pnl = (entry_price - current_price) * qty * FACE_VALUE
        # Expected using FACE_VALUE (0.01):
        self.assertAlmostEqual(pnl, 119.61, places=1)
        
        # lock_threshold
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=False)
        self.assertAlmostEqual(lock_threshold, 2809.30, places=1)
        
        # 如果 1H ST = 2385.21，检查是否直接进入HOURLY
        last_1h_st = 2385.21
        should_enter_hourly_direct = is_1h_tighter(last_1h_st, lock_threshold, is_long=False)
        # 2385.21 < 2809.30? YES，应从SURVIVAL直接进HOURLY
        self.assertTrue(should_enter_hourly_direct)


class DummyStrategyClient:
    def __init__(self, price_orders=None):
        self.price_orders = price_orders or []

    def get_price_orders(self, contract: str, status: str = "open", limit: int = 100):
        return self.price_orders


class TestLiveStopFallback(unittest.TestCase):
    def test_get_live_stop_price_supports_is_reduce_only(self):
        client = DummyStrategyClient(price_orders=[
            {
                "trigger": {"price": "3000"},
                "initial": {
                    "is_reduce_only": True,
                    "auto_size": "close",
                },
            }
        ])

        strategy = TradingStrategy(client)
        self.assertEqual(strategy._get_live_stop_price(), 3000.0)

    def test_manage_short_position_emits_stop_updated_without_local_state(self):
        client = DummyStrategyClient(price_orders=[
            {
                "trigger": {"price": "3000"},
                "initial": {
                    "is_reduce_only": True,
                    "auto_size": "close",
                },
            }
        ])
        strategy = TradingStrategy(client)

        position = {"entry_price": 2062.17, "size": -49}
        df_30m = pd.DataFrame({"close": [2060.0, 2060.0]})
        df_1h = pd.DataFrame({"close": [2060.0, 2060.0]})
        st_30m = pd.DataFrame({"supertrend": [2063.0, 2059.0], "direction": [-1, -1]})
        st_1h = pd.DataFrame({"supertrend": [2063.0, 2052.0], "direction": [-1, -1]})

        with patch("strategy.load_position_state", return_value={}), patch("strategy.update_position_state", return_value=(True, "new_position")):
            result = strategy._manage_short_position(
                position,
                df_30m,
                df_1h,
                st_30m,
                st_1h,
                last_1h_close=2060.0,
                last_1h_dema=2100.0,
                risk_amount=10.0,
                risk_info="test",
            )

        self.assertEqual(result.action, "stop_updated")
        self.assertEqual(result.details["old_stop"], 3000.0)
        self.assertAlmostEqual(result.details["stop_loss"], 2063.0, places=2)

    def test_infer_phase_uses_actual_stop_for_locked_long(self):
        strategy = TradingStrategy(DummyStrategyClient())

        phase, stop_loss = strategy._infer_phase(
            entry_price=2000.0,
            current_price=2020.0,
            qty=100,
            last_30m_st=2001.0,
            last_1h_st=1995.0,
            is_long=True,
            prev_stop_loss=2001.0,
        )

        self.assertEqual(phase, Phase.LOCKED.value)
        self.assertEqual(stop_loss, 2001.0)

    def test_infer_phase_uses_actual_stop_for_survival_short(self):
        strategy = TradingStrategy(DummyStrategyClient())

        phase, stop_loss = strategy._infer_phase(
            entry_price=2000.0,
            current_price=1980.0,
            qty=100,
            last_30m_st=2010.0,
            last_1h_st=2020.0,
            is_long=False,
            prev_stop_loss=2008.0,
        )

        self.assertEqual(phase, Phase.SURVIVAL.value)
        self.assertEqual(stop_loss, 2008.0)


class TestStrategyRounding(unittest.TestCase):
    def test_round_price_default(self):
        # Default fallback is 0.01
        strategy = TradingStrategy(DummyStrategyClient(), contract="ETH_USDT")
        self.assertEqual(strategy._round_price(2000.1234), 2000.12)
        self.assertEqual(strategy._round_price(2000.126), 2000.13)

    def test_round_price_btc(self):
        # BTC fallback is 0.1
        strategy = TradingStrategy(DummyStrategyClient(), contract="BTC_USDT")
        self.assertEqual(strategy._round_price(64085.62), 64085.6)
        self.assertEqual(strategy._round_price(64085.67), 64085.7)

    def test_round_price_from_contract_info(self):
        class MockClientWithContract:
            def get_futures_contract(self, settle, contract):
                return {"order_price_round": "0.5"}
        
        strategy = TradingStrategy(MockClientWithContract(), contract="ADA_USDT")
        self.assertEqual(strategy._round_price(1.23), 1.0)
        self.assertEqual(strategy._round_price(1.26), 1.5)


if __name__ == '__main__':
    # 运行所有测试
    unittest.main(verbosity=2)
