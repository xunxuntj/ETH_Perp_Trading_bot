"""
持仓状态管理测试
验证阶段变化和止损调整的检测和通知功能
"""

import os
import time
import json
import unittest
from position_state import (
    update_position_state, load_position_state, save_position_state,
    clear_position_state, clear_all_position_state, POSITION_STATE_FILE
)


class TestPositionState(unittest.TestCase):
    """持仓状态管理测试"""
    
    def setUp(self):
        """测试前清理状态文件"""
        clear_all_position_state()
    
    def tearDown(self):
        """测试后清理状态文件"""
        clear_all_position_state()
    
    def test_1_first_update_no_change(self):
        """测试第一次更新应该没有变化（前一次状态不存在）"""
        print("\n【测试 1】第一次更新应该没有变化")
        
        has_change, change_type = update_position_state(
            direction="long",
            phase="SURVIVAL",
            stop_loss=2000.0,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        self.assertFalse(has_change)
        self.assertEqual(change_type, "")
        
        # 验证状态已保存
        state = load_position_state()
        self.assertIn("long", state)
        self.assertEqual(state["long"]["phase"], "SURVIVAL")
        self.assertEqual(state["long"]["stop_loss"], 2000.0)
        print("✅ 第一次更新正确：无变化，状态已保存")
    
    def test_2_stop_loss_updated(self):
        """测试止损更新（超过 0.01 差异）"""
        print("\n【测试 2】检测止损变化")
        
        # 第一次更新
        update_position_state(
            direction="long",
            phase="SURVIVAL",
            stop_loss=2000.0,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        time.sleep(0.1)  # 模拟时间推进
        
        # 第二次更新 - 止损改变
        has_change, change_type = update_position_state(
            direction="long",
            phase="SURVIVAL",
            stop_loss=1995.5,  # 差异 4.5 > 0.01
            entry_price=2010.0,
            current_time=time.time()
        )
        
        self.assertTrue(has_change)
        self.assertEqual(change_type, "stop_updated")
        print("✅ 止损变化检测成功：action='stop_updated'")
    
    def test_3_enter_locked_phase(self):
        """测试进入锁利期（SURVIVAL → LOCKED）"""
        print("\n【测试 3】检测进入锁利期")
        
        # 第一次更新 - 生存期
        update_position_state(
            direction="long",
            phase="SURVIVAL",
            stop_loss=2000.0,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        time.sleep(0.1)
        
        # 第二次更新 - 切换到锁利期（浮盈超过 50U）
        has_change, change_type = update_position_state(
            direction="long",
            phase="LOCKED",
            stop_loss=2000.0,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        self.assertTrue(has_change)
        self.assertEqual(change_type, "enter_locked")
        print("✅ 进入锁利期检测成功：action='enter_locked'")
    
    def test_4_switch_1h_phase(self):
        """测试切换到小时线（LOCKED → HOURLY）"""
        print("\n【测试 4】检测切换至小时线轨道")
        
        # 第一次更新 - 锁利期
        update_position_state(
            direction="long",
            phase="LOCKED",
            stop_loss=2000.0,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        time.sleep(0.1)
        
        # 第二次更新 - 切换到小时线
        has_change, change_type = update_position_state(
            direction="long",
            phase="HOURLY",
            stop_loss=2000.0,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        self.assertTrue(has_change)
        self.assertEqual(change_type, "switch_1h")
        print("✅ 切换至小时线检测成功：action='switch_1h'")
    
    def test_5_long_and_short_separate(self):
        """测试多空持仓分别跟踪"""
        print("\n【测试 5】多空持仓分别跟踪")
        
        # 开多单
        update_position_state(
            direction="long",
            phase="SURVIVAL",
            stop_loss=2000.0,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        # 开空单
        update_position_state(
            direction="short",
            phase="SURVIVAL",
            stop_loss=2100.0,
            entry_price=2090.0,
            current_time=time.time()
        )
        
        # 验证两个持仓都被保存
        state = load_position_state()
        self.assertIn("long", state)
        self.assertIn("short", state)
        self.assertEqual(state["long"]["entry_price"], 2010.0)
        self.assertEqual(state["short"]["entry_price"], 2090.0)
        print("✅ 多空持仓分别跟踪成功")
    
    def test_6_stop_loss_small_change(self):
        """测试止损微小变化（≤0.01 不触发）"""
        print("\n【测试 6】止损微小变化不触发通知")
        
        # 第一次更新
        update_position_state(
            direction="long",
            phase="SURVIVAL",
            stop_loss=2000.00,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        time.sleep(0.1)
        
        # 第二次更新 - 止损变化 < 0.01
        has_change, change_type = update_position_state(
            direction="long",
            phase="SURVIVAL",
            stop_loss=2000.005,  # 差异 0.005 < 0.01
            entry_price=2010.0,
            current_time=time.time()
        )
        
        self.assertFalse(has_change)
        self.assertEqual(change_type, "")
        print("✅ 微小变化正确处理：不触发通知")
    
    def test_7_clear_position_state(self):
        """测试平仓清除状态"""
        print("\n【测试 7】平仓清除状态")
        
        # 添加多空持仓
        update_position_state("long", "SURVIVAL", 2000.0, 2010.0, time.time())
        update_position_state("short", "SURVIVAL", 2100.0, 2090.0, time.time())
        
        # 验证两个持仓都存在
        state = load_position_state()
        self.assertEqual(len(state), 2)
        
        # 清除多单
        clear_position_state("long")
        state = load_position_state()
        self.assertEqual(len(state), 1)
        self.assertNotIn("long", state)
        self.assertIn("short", state)
        print("✅ 平仓清除状态成功")
    
    def test_8_survival_to_hourly(self):
        """测试从生存期直接到小时线（跳过锁利期）"""
        print("\n【测试 8】生存期到小时线（跳过锁利期）")
        
        # 第一次更新 - 生存期
        update_position_state(
            direction="long",
            phase="SURVIVAL",
            stop_loss=2000.0,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        time.sleep(0.1)
        
        # 第二次更新 - 直接到小时线
        has_change, change_type = update_position_state(
            direction="long",
            phase="HOURLY",
            stop_loss=2000.0,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        self.assertTrue(has_change)
        self.assertEqual(change_type, "switch_1h")
        print("✅ 直接到小时线检测成功：action='switch_1h'")
    
    def test_9_multiple_updates_same_phase(self):
        """测试同一阶段多次更新（止损不变则无通知）"""
        print("\n【测试 9】同一阶段多次更新无变化")
        
        # 第一次更新
        update_position_state("long", "LOCKED", 2000.0, 2010.0, time.time())
        
        time.sleep(0.1)
        
        # 第二次更新 - 同一阶段，止损相同
        has_change, change_type = update_position_state(
            direction="long",
            phase="LOCKED",
            stop_loss=2000.0,
            entry_price=2010.0,
            current_time=time.time()
        )
        
        self.assertFalse(has_change)
        self.assertEqual(change_type, "")
        print("✅ 同一阶段无变化正确处理")


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("持仓状态管理单元测试")
    print("=" * 60)
    
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPositionState)
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 输出总结
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("✅ 所有测试通过！")
    else:
        print(f"❌ {len(result.failures)} 个失败，{len(result.errors)} 个错误")
    print("=" * 60)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
