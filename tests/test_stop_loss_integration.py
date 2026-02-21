"""
止损跟踪系统集成测试
模拟完整的持仓周期：开仓 → 阶段转换 → 平仓
"""

import os
import json
import time
from unittest.mock import Mock, patch
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np

# 导入模块
from position_state import (
    update_position_state, load_position_state,
    clear_all_position_state, POSITION_STATE_FILE
)


@dataclass
class TradeResult:
    """交易结果"""
    action: str
    message: str
    details: dict


class Phase(Enum):
    """交易阶段"""
    SURVIVAL = "SURVIVAL"    # 生存期
    LOCKED = "LOCKED"        # 锁利期
    HOURLY = "HOURLY"        # 小时线轨道


def simulate_position_cycle():
    """
    模拟完整的持仓周期
    周期1: 开仓 (SURVIVAL) → 无变化
    周期2: 阶段升级 (SURVIVAL → LOCKED) → 推送 "enter_locked"
    周期3: 进一步升级 (LOCKED → HOURLY) → 推送 "switch_1h"
    周期4: 止损调整 (HOURLY 止损变化) → 推送 "stop_updated"
    周期5: 持续持仓 (HOURLY，无变化) → 推送 "hold"
    """
    print("\n" + "=" * 70)
    print("【集成测试】止损跟踪完整周期模拟")
    print("=" * 70)
    
    clear_all_position_state()
    
    # 初始化
    entry_price = 2010.0
    results = []
    
    print("\n【周期 1】首次进入持仓（生存期）")
    print("-" * 70)
    
    # 周期1: 开仓，进入生存期
    cycle_1_price = 2020.0  # 浮盈 +50U
    cycle_1_stop = 2000.0
    cycle_1_phase = Phase.SURVIVAL.value
    
    has_change, action = update_position_state(
        direction="long",
        phase=cycle_1_phase,
        stop_loss=cycle_1_stop,
        entry_price=entry_price,
        current_time=time.time()
    )
    
    result_1 = TradeResult(
        action=action if action else "open_long",
        message=f"""✅ 已开多单
• 入场: {entry_price:.2f} | 当前: {cycle_1_price:.2f}
• 阶段: 🔵 生存期 | 止损: {cycle_1_stop:.2f}
• 浮盈: {(cycle_1_price - entry_price) * 10:.2f}U""",
        details={"phase": cycle_1_phase, "stop_loss": cycle_1_stop, "action_type": action}
    )
    
    results.append(result_1)
    print(f"📊 Action: {result_1.action}")
    print(f"💬 Message:\n{result_1.message}")
    print(f"📈 变化检测: has_change={has_change}, action='{action}'")
    
    time.sleep(0.2)  # 模拟 30 分钟
    
    print("\n【周期 2】浮盈积累，进入锁利期")
    print("-" * 70)
    
    # 周期2: 浮盈超过 50U，进入锁利期
    cycle_2_price = 2070.0  # 浮盈 +60U
    cycle_2_stop = 2010.0
    cycle_2_phase = Phase.LOCKED.value
    
    has_change, action = update_position_state(
        direction="long",
        phase=cycle_2_phase,
        stop_loss=cycle_2_stop,
        entry_price=entry_price,
        current_time=time.time()
    )
    
    result_2 = TradeResult(
        action=action,
        message=f"""🟡 已进入锁利期
• 入场: {entry_price:.2f} | 当前: {cycle_2_price:.2f}
• 阶段: 🟡 锁利期 | 止损: {cycle_2_stop:.2f}
• 浮盈: {(cycle_2_price - entry_price) * 10:.2f}U
• 说明: 浮盈已超过 50U，切换至锁利策略""",
        details={"phase": cycle_2_phase, "stop_loss": cycle_2_stop, "action_type": action}
    )
    
    results.append(result_2)
    print(f"📊 Action: {result_2.action}")
    print(f"💬 Message:\n{result_2.message}")
    print(f"✅ 变化检测: has_change={has_change}, action='{action}'")
    assert action == "enter_locked", f"❌ 预期 'enter_locked'，获得 '{action}'"
    
    time.sleep(0.2)
    
    print("\n【周期 3】1H ST 转向上升，切换小时线轨道")
    print("-" * 70)
    
    # 周期3: 1H ST 转向上升，切换小时线
    cycle_3_price = 2100.0  # 浮盈 +90U
    cycle_3_stop = 2050.0  # 1H ST 更高
    cycle_3_phase = Phase.HOURLY.value
    
    has_change, action = update_position_state(
        direction="long",
        phase=cycle_3_phase,
        stop_loss=cycle_3_stop,
        entry_price=entry_price,
        current_time=time.time()
    )
    
    result_3 = TradeResult(
        action=action,
        message=f"""🟣 已切换至小时线轨道
• 入场: {entry_price:.2f} | 当前: {cycle_3_price:.2f}
• 阶段: 🟣 换轨期 | 止损: {cycle_3_stop:.2f}
• 浮盈: {(cycle_3_price - entry_price) * 10:.2f}U
• 说明: 1H ST已转向上升，以 1H ST 作为止损参考""",
        details={"phase": cycle_3_phase, "stop_loss": cycle_3_stop, "action_type": action}
    )
    
    results.append(result_3)
    print(f"📊 Action: {result_3.action}")
    print(f"💬 Message:\n{result_3.message}")
    print(f"✅ 变化检测: has_change={has_change}, action='{action}'")
    assert action == "switch_1h", f"❌ 预期 'switch_1h'，获得 '{action}'"
    
    time.sleep(0.2)
    
    print("\n【周期 4】1H ST 继续上升，止损被调整")
    print("-" * 70)
    
    # 周期4: 1H ST 继续上升，止损被调整
    cycle_4_price = 2120.0  # 浮盈 +110U
    cycle_4_stop = 2080.0   # 1H ST 又上升了（差异 > 0.01）
    cycle_4_phase = Phase.HOURLY.value
    
    has_change, action = update_position_state(
        direction="long",
        phase=cycle_4_phase,
        stop_loss=cycle_4_stop,
        entry_price=entry_price,
        current_time=time.time()
    )
    
    result_4 = TradeResult(
        action=action,
        message=f"""⚠️  止损已调整
• 入场: {entry_price:.2f} | 当前: {cycle_4_price:.2f}
• 新止损: {cycle_4_stop:.2f} | 浮盈: {(cycle_4_price - entry_price) * 10:.2f}U
• 阶段: 🟣 换轨期""",
        details={"phase": cycle_4_phase, "stop_loss": cycle_4_stop, "action_type": action}
    )
    
    results.append(result_4)
    print(f"📊 Action: {result_4.action}")
    print(f"💬 Message:\n{result_4.message}")
    print(f"✅ 变化检测: has_change={has_change}, action='{action}'")
    assert action == "stop_updated", f"❌ 预期 'stop_updated'，获得 '{action}'"
    
    time.sleep(0.2)
    
    print("\n【周期 5】持续持仓，无状态变化")
    print("-" * 70)
    
    # 周期5: 继续持仓，无变化
    cycle_5_price = 2130.0  # 浮盈 +120U
    cycle_5_stop = 2080.0   # 止损不变
    cycle_5_phase = Phase.HOURLY.value
    
    has_change, action = update_position_state(
        direction="long",
        phase=cycle_5_phase,
        stop_loss=cycle_5_stop,
        entry_price=entry_price,
        current_time=time.time()
    )
    
    result_5 = TradeResult(
        action=action if action else "hold",
        message=f"""✅ 持仓中
• 方向: 多 | 阶段: 🟣 换轨期
• 入场: {entry_price:.2f} | 当前: {cycle_5_price:.2f}
• 止损: {cycle_5_stop:.2f} | 浮盈: {(cycle_5_price - entry_price) * 10:.2f}U
• 离场条件: 1H ST 变红""",
        details={"phase": cycle_5_phase, "stop_loss": cycle_5_stop, "action_type": action}
    )
    
    results.append(result_5)
    print(f"📊 Action: {result_5.action}")
    print(f"💬 Message:\n{result_5.message}")
    print(f"✅ 变化检测: has_change={has_change}, action='{action}'")
    assert action == "", f"❌ 预期无变化 ''，获得 '{action}'"
    
    # 输出总结
    print("\n" + "=" * 70)
    print("【集成测试总结】")
    print("=" * 70)
    print("\n完整持仓周期结果：\n")
    
    for i, result in enumerate(results, 1):
        action_display = f"'{result.action}'" if result.action else "'hold'"
        print(f"周期 {i}: action={action_display:20} | phase={result.details.get('phase'):8}")
    
    print("\n预期的通知序列：")
    print("  1. 开仓 → action='open_long'")
    print("  2. 阶段升级 → action='enter_locked'   ✅ 已校验")
    print("  3. 轨道切换 → action='switch_1h'      ✅ 已校验")
    print("  4. 止损调整 → action='stop_updated'   ✅ 已校验")
    print("  5. 持续持仓 → action='hold'           ✅ 已校验")
    
    print("\n✅ 集成测试通过！系统正确处理了：")
    print("   • 阶段变化检测 (SURVIVAL → LOCKED)")
    print("   • 轨道切换检测 (LOCKED → HOURLY)")
    print("   • 止损调整检测 (同阶段的止损变化)")
    print("   • 无变化状态 (同阶段同止损)")
    
    print("\n📊 持仓状态文件内容：")
    state = load_position_state()
    print(json.dumps(state, indent=2))
    
    return True


def simulate_short_position():
    """模拟空仓周期"""
    print("\n" + "=" * 70)
    print("【集成测试】空仓周期")
    print("=" * 70)
    
    clear_all_position_state()
    
    # 空仓开仓
    entry_price = 2050.0
    current_price = 2030.0
    stop_loss = 2100.0
    
    print("\n【周期 1】开空单，生存期")
    has_change, action = update_position_state(
        direction="short",
        phase=Phase.SURVIVAL.value,
        stop_loss=stop_loss,
        entry_price=entry_price,
        current_time=time.time()
    )
    print(f"✅ 开空单: action='{action}', has_change={has_change}")
    assert action == ""
    
    time.sleep(0.1)
    
    print("\n【周期 2】浮盈 +60U，进入锁利期")
    has_change, action = update_position_state(
        direction="short",
        phase=Phase.LOCKED.value,
        stop_loss=2030.0,
        entry_price=entry_price,
        current_time=time.time()
    )
    print(f"✅ 进入锁利期: action='{action}', has_change={has_change}")
    assert action == "enter_locked"
    
    print("\n✅ 空仓周期测试通过！")
    return True


def simulate_long_and_short_parallel():
    """模拟多空同时持仓"""
    print("\n" + "=" * 70)
    print("【集成测试】多空同时持仓")
    print("=" * 70)
    
    clear_all_position_state()
    
    print("\n同时开1多1空：")
    
    # 开多
    update_position_state(
        direction="long",
        phase=Phase.SURVIVAL.value,
        stop_loss=2000.0,
        entry_price=2010.0,
        current_time=time.time()
    )
    print("✅ 多单: 入场 2010")
    
    # 开空（不同的阶段）
    update_position_state(
        direction="short",
        phase=Phase.LOCKED.value,
        stop_loss=2100.0,
        entry_price=2090.0,
        current_time=time.time()
    )
    print("✅ 空单: 入场 2090")
    
    # 验证分别跟踪
    state = load_position_state()
    assert "long" in state and "short" in state
    assert state["long"]["entry_price"] == 2010.0
    assert state["short"]["entry_price"] == 2090.0
    assert state["long"]["phase"] == "SURVIVAL"
    assert state["short"]["phase"] == "LOCKED"
    
    print("\n多空持仓状态：")
    for direction, data in state.items():
        print(f"  {direction}: 入场={data['entry_price']}, 阶段={data['phase']}")
    
    print("\n✅ 多空并行跟踪正确！")
    return True


if __name__ == "__main__":
    try:
        print("\n🚀 开始止损跟踪系统集成测试...\n")
        
        # 测试1: 完整的多仓周期
        success_1 = simulate_position_cycle()
        
        # 测试2: 空仓周期
        success_2 = simulate_short_position()
        
        # 测试3: 多空并行
        success_3 = simulate_long_and_short_parallel()
        
        # 总结
        print("\n" + "=" * 70)
        print("【总体测试结果】")
        print("=" * 70)
        
        if success_1 and success_2 and success_3:
            print("\n✅ 所有集成测试通过！")
            print("\n系统已验证可以：")
            print("  ✓ 检测阶段状态变化")
            print("  ✓ 检测止损价格调整")
            print("  ✓ 分别跟踪多空持仓")
            print("  ✓ 正确生成 action 类型")
            print("\n🎉 止损跟踪系统已做好生产部署准备！")
            exit(0)
        else:
            print("\n❌ 某些测试失败")
            exit(1)
            
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
    finally:
        clear_all_position_state()
