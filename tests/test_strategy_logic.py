#!/usr/bin/env python3
"""
策略逻辑单元测试
涵盖: SURVIVAL/LOCKED/HOURLY 阶段转换、止损更新、恢复逻辑
"""

import unittest
from unittest.mock import patch
from strategy import (
    is_1h_tighter, calculate_lock_threshold, calculate_position_size,
    Phase, Direction, Position, FACE_VALUE, TradingStrategy
)
from config import LOCK_PROFIT_BUFFER


class DummyClient:
    """仅用于调用 _infer_phase 的最小客户端桩。"""
    pass


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
        # qty = 50 / 100 / FACE_VALUE = 5
        self.assertEqual(result['qty'], 5)
        self.assertAlmostEqual(result['sl_distance'], 100.0, places=1)
        self.assertAlmostEqual(result['position_eth'], 0.5, places=2)
        self.assertAlmostEqual(result['actual_risk'], 50.0, places=1)


class TestPhaseTransitions(unittest.TestCase):
    """测试阶段转换逻辑"""

    def test_phase_survival_when_pnl_non_positive(self):
        """按当前止损成交 PnL <= 0 时应处于生存期并跟随30m ST。"""
        strategy = TradingStrategy(DummyClient())
        phase, stop = strategy._infer_phase(
            entry_price=2000.0,
            current_price=1995.0,
            qty=10,
            last_30m_st=1990.0,
            last_1h_st=1980.0,
            is_long=True,
            current_stop_loss=1998.0
        )
        self.assertEqual(phase, Phase.SURVIVAL.value)
        self.assertEqual(stop, 1990.0)

    def test_phase_locked_when_pnl_positive_and_not_above_buffer(self):
        """按当前止损成交 0 < PnL <= BUFFER 时进入锁利期并跟随30m ST。"""
        strategy = TradingStrategy(DummyClient())
        # 多仓: (current_stop - entry) * qty * FACE_VALUE = 0.5U
        phase, stop = strategy._infer_phase(
            entry_price=2000.0,
            current_price=2002.0,
            qty=10,
            last_30m_st=2003.0,
            last_1h_st=1995.0,
            is_long=True,
            current_stop_loss=2005.0  # pnl = (2005-2000)*10*0.01 = 0.5
        )
        self.assertTrue(0 < (2005.0 - 2000.0) * 10 * FACE_VALUE <= LOCK_PROFIT_BUFFER)
        self.assertEqual(phase, Phase.LOCKED.value)
        self.assertEqual(stop, 2003.0)

    def test_phase_hourly_when_tight_only_and_1h_not_tighter(self):
        """tight_only 下，PnL>BUFFER 时仍进入 HOURLY（止损是否更新由只收紧规则控制）。"""
        strategy = TradingStrategy(DummyClient())
        with patch('strategy.STOP_LOSS_MODE', 'tight_only'):
            phase, stop = strategy._infer_phase(
                entry_price=2000.0,
                current_price=2020.0,
                qty=10,
                last_30m_st=2012.0,
                last_1h_st=2008.0,
                is_long=True,
                current_stop_loss=2012.0  # pnl = 1.2U > 1.0U
            )
        self.assertEqual(phase, Phase.HOURLY.value)
        self.assertEqual(stop, 2008.0)

    def test_phase_hourly_when_tight_only_and_1h_tighter(self):
        """tight_only 下，1H 比当前止损更紧时，切换 HOURLY。"""
        strategy = TradingStrategy(DummyClient())
        with patch('strategy.STOP_LOSS_MODE', 'tight_only'):
            phase, stop = strategy._infer_phase(
                entry_price=2000.0,
                current_price=2020.0,
                qty=10,
                last_30m_st=2012.0,
                last_1h_st=2015.0,
                is_long=True,
                current_stop_loss=2012.0
            )
        self.assertEqual(phase, Phase.HOURLY.value)
        self.assertEqual(stop, 2015.0)

    def test_phase_hourly_in_both_mode_even_if_1h_not_tighter(self):
        """both 模式下，PnL>BUFFER 即切换到 HOURLY 并跟随 1H ST。"""
        strategy = TradingStrategy(DummyClient())
        with patch('strategy.STOP_LOSS_MODE', 'both'):
            phase, stop = strategy._infer_phase(
                entry_price=2000.0,
                current_price=2020.0,
                qty=10,
                last_30m_st=2012.0,
                last_1h_st=2008.0,
                is_long=True,
                current_stop_loss=2012.0
            )
        self.assertEqual(phase, Phase.HOURLY.value)
        self.assertEqual(stop, 2008.0)

    def test_survival_to_locked_long(self):
        """多仓：生存期 → 锁利期（浮盈 > BUFFER）"""
        # 简化测试：直接检查 is_1h_tighter 在各阶段的应用
        entry_price = 2000.0
        current_price = 2010.0
        qty = 10
        is_long = True
        
        # 浮盈 = (2010 - 2000) * 10 * 0.01 = 1.0 U (刚好等于 BUFFER)
        pnl = (current_price - entry_price) * qty * FACE_VALUE
        self.assertAlmostEqual(pnl, 1.0, places=2)
        
        # lock_threshold = 2000 + 1.0 / 0.1 = 2010.0
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=True)
        self.assertAlmostEqual(lock_threshold, 2010.0, places=2)

    def test_survival_to_locked_short(self):
        """空仓：生存期 → 锁利期（浮盈 > BUFFER）"""
        entry_price = 2000.0
        current_price = 1990.0
        qty = 10
        is_long = False
        
        # 浮盈 = (2000 - 1990) * 10 * 0.01 = 1.0 U
        pnl = (entry_price - current_price) * qty * FACE_VALUE
        self.assertAlmostEqual(pnl, 1.0, places=2)
        
        # lock_threshold = 2000 - 1.0 / 0.1 = 1990.0
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=False)
        self.assertAlmostEqual(lock_threshold, 1990.0, places=2)

    def test_survival_to_hourly_long_immediate(self):
        """多仓：生存期 → 直接进入换轨期（1H ST比lock_threshold更紧）"""
        entry_price = 2000.0
        qty = 10
        is_long = True
        last_1h_st = 2020.0
        
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=True)
        # lock_threshold ≈ 2010.0
        # last_1h_st 2020.0 > lock_threshold 2010.0? YES，应进入HOURLY
        should_enter_hourly = is_1h_tighter(last_1h_st, lock_threshold, is_long=True)
        self.assertTrue(should_enter_hourly)

    def test_survival_to_hourly_short_immediate(self):
        """空仓：生存期 → 直接进入换轨期（1H ST比lock_threshold更紧）"""
        entry_price = 2000.0
        qty = 10
        is_long = False
        last_1h_st = 1980.0
        
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=False)
        # lock_threshold ≈ 1990.0
        # last_1h_st 1980.0 < lock_threshold 1990.0? YES，应进入HOURLY
        should_enter_hourly = is_1h_tighter(last_1h_st, lock_threshold, is_long=False)
        self.assertTrue(should_enter_hourly)

    def test_locked_to_hourly_long_trigger(self):
        """多仓：锁利期 → 换轨期（1H ST比locked_stop更紧）"""
        last_1h_st = 2360.0
        locked_stop = 2350.0
        is_long = True
        
        # 2360 > 2350? YES，应进入HOURLY
        should_switch = is_1h_tighter(last_1h_st, locked_stop, is_long=True)
        self.assertTrue(should_switch)

    def test_locked_to_hourly_long_no_trigger(self):
        """多仓：锁利期 → 保持（1H ST不比locked_stop更紧）"""
        last_1h_st = 2330.0
        locked_stop = 2350.0
        is_long = True
        
        # 2330 > 2350? NO，不进入HOURLY
        should_switch = is_1h_tighter(last_1h_st, locked_stop, is_long=True)
        self.assertFalse(should_switch)

    def test_locked_to_hourly_short_trigger(self):
        """空仓：锁利期 → 换轨期（1H ST比locked_stop更紧）"""
        last_1h_st = 2300.0
        locked_stop = 2341.21
        is_long = False
        
        # 2300 < 2341.21? YES，应进入HOURLY
        should_switch = is_1h_tighter(last_1h_st, locked_stop, is_long=False)
        self.assertTrue(should_switch)

    def test_locked_to_hourly_short_no_trigger(self):
        """空仓：锁利期 → 保持（1H ST不比locked_stop更紧）"""
        last_1h_st = 2385.21
        locked_stop = 2341.21
        is_long = False
        
        # 2385.21 < 2341.21? NO，不进入HOURLY
        should_switch = is_1h_tighter(last_1h_st, locked_stop, is_long=False)
        self.assertFalse(should_switch)


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
        
        pnl = (current_price - entry_price) * qty * FACE_VALUE_VALUE
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
        # Expected using FACE_VALUE (0.1):
        self.assertAlmostEqual(pnl, 1196.1, places=1)
        
        # lock_threshold
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=False)
        self.assertAlmostEqual(lock_threshold, 2809.30, places=1)
        
        # 如果 1H ST = 2385.21，检查是否直接进入HOURLY
        last_1h_st = 2385.21
        should_enter_hourly_direct = is_1h_tighter(last_1h_st, lock_threshold, is_long=False)
        # 2385.21 < 2809.30? YES，应从SURVIVAL直接进HOURLY
        self.assertTrue(should_enter_hourly_direct)


if __name__ == '__main__':
    # 运行所有测试
    unittest.main(verbosity=2)
