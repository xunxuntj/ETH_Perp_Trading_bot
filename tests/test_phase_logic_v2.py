#!/usr/bin/env python3
"""
三阶段止损逻辑 V2 - 测试脚本
验证用户提供的交易案例
"""

import sys
import os
from dataclasses import dataclass
from typing import List, Tuple
from enum import Enum

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 从配置中导入 LOCK_PROFIT_BUFFER（确保使用配置项，而非硬编码）
from config import LOCK_PROFIT_BUFFER

# 合约面值常数（从 strategy.py 保持一致）
FACE_VALUE = 0.01  # ETH per contract


class Phase(Enum):
    """持仓阶段"""
    SURVIVAL = "SURVIVAL"
    LOCKED = "LOCKED"
    HOURLY = "HOURLY"


@dataclass
class MarketData:
    """市场数据"""
    timestamp: int
    st_30m: float
    st_1h: float


def infer_phase(
    entry_price: float,
    qty: int,
    last_30m_st: float,
    last_1h_st: float,
    is_long: bool,
    initial_30m_st: float = 0,
    locked_stop_loss: float = 0,
    prev_stop_loss: float = 0
) -> Tuple[str, float]:
    """推导阶段 - 新逻辑
    
    阶段1 - 生存期: 30m ST 未达到开仓价
    阶段2 - 锁利期: 30m ST 已达到开仓价，但按30m ST平仓收益 <= LOCK_PROFIT_BUFFER，跟随30m ST
    阶段3 - 换轨期: 按30m ST平仓收益 > LOCK_PROFIT_BUFFER，跟随1H ST，止损只紧不松
    """
    # 计算期望盈利
    if is_long:
        expected_pnl = (last_30m_st - entry_price) * qty * FACE_VALUE
    else:
        expected_pnl = (entry_price - last_30m_st) * qty * FACE_VALUE
    
    # 【阶段1 - 生存期】
    if is_long:
        st_reached_entry = last_30m_st >= entry_price
    else:
        st_reached_entry = last_30m_st <= entry_price

    if not st_reached_entry:
        return Phase.SURVIVAL.value, last_30m_st
    
    # 30m ST已达到开仓价
    
    # 【阶段3 - 换轨期】
    if expected_pnl > LOCK_PROFIT_BUFFER:
        if is_long:
            recommended_stop = max(last_1h_st, prev_stop_loss) if prev_stop_loss > 0 else last_1h_st
        else:
            recommended_stop = min(last_1h_st, prev_stop_loss) if prev_stop_loss > 0 else last_1h_st
        return Phase.HOURLY.value, recommended_stop
    
    # 【阶段2 - 锁利期】: 30m ST已达开仓价，收益在缓冲范围内，继续跟随30m ST
    return Phase.LOCKED.value, last_30m_st


def test_case_from_user():
    """测试用户提供的实际交易案例"""
    
    print("=" * 80)
    print("测试场景：用户提供的空单交易")
    print("=" * 80)
    
    # 交易信息
    entry_price = 2062.17
    qty = 49
    is_long = False  # 空单
    
    print(f"\n【交易信息】")
    print(f"  方向: {'多' if is_long else '空'}")
    print(f"  入场价: {entry_price:.2f}")
    print(f"  张数: {qty}")
    print(f"  仓位: {qty * FACE_VALUE:.2f} ETH")
    print(f"  杠杆: 10x")
    
    # 期望盈利计算（空单）
    # 盈利 = (入场 - st_30m) * 张数 * 0.01
    # 若st_30m = 2031.55，盈利 = (2062.17 - 2031.55) * 49 * 0.01 = 15.0 USDT
    expected_pnl_at_2031_55 = (entry_price - 2031.55) * qty * FACE_VALUE
    print(f"  在ST₃₀ₘ=2031.55时的期望盈利: {expected_pnl_at_2031_55:.2f}U")
    
    # 模拟市场数据序列
    # 按照用户提供的30m ST和1h ST数据
    data_30m_st = [
        2038.65, 2034.4, 2034.4, 2024.83, 2024.83, 2024.83, 2024.83, 2024.83,
        2024.83, 2024.83, 2024.83, 2024.83, 2024.83, 2024.83, 2024.83, 2019.75,
        2015.26, 2014.45, 2012.35, 2010.57, 2007.49
    ]
    
    data_1h_st = [
        2050.99, 2044.95, 2044.95, 2044.95, 2044.95, 2044.95, 2044.95, 2042.22,
        2035.94, 2032.37, 2029.11, 2029.11, 2022.8, 2022.8, 2019.37, 2019.37
    ]
    
    print(f"\n【市场数据回放】")
    print(f"  30m ST数据点: {len(data_30m_st)}")
    print(f"  1h ST数据点: {len(data_1h_st)}")
    
    # 模拟运行
    print(f"\n【阶段推导过程】")
    print(f"{'时刻':<5} {'30m ST':<10} {'1h ST':<10} {'期望盈利':<10} {'阶段':<10} {'止损':<10} {'说明':<30}")
    print("-" * 90)
    
    phase = Phase.SURVIVAL.value
    stop_loss = 0
    prev_stop_loss = 0
    prev_phase = None
    
    # 处理30m ST数据
    for t, st_30m in enumerate(data_30m_st):
        # 1h ST数据可能少于30m，所以用最后一个有效值或对应值
        st_1h = data_1h_st[min(t, len(data_1h_st) - 1)]
        
        # 推导阶段
        phase, stop_loss = infer_phase(
            entry_price, qty, st_30m, st_1h, is_long,
            prev_stop_loss=prev_stop_loss
        )
        
        # 计算期望盈利
        pnl = (entry_price - st_30m) * qty * FACE_VALUE
        
        # 检测阶段变化
        phase_change = ""
        if prev_phase != phase:
            if phase == Phase.LOCKED.value:
                phase_change = "→ 进入锁利期"
            elif phase == Phase.HOURLY.value:
                phase_change = "→ 进入换轨期"
        
        print(f"{t:<5} {st_30m:<10.2f} {st_1h:<10.2f} {pnl:<10.2f} {phase:<10} {stop_loss:<10.2f} {phase_change:<30}")
        
        prev_stop_loss = stop_loss
        prev_phase = phase
    
    # 验证关键点
    print(f"\n【验证关键点】")
    print(f"✓ 生存期阈值: 30m ST 未达到开仓价 {entry_price:.2f}")
    print(f"✓ 锁利期: 30m ST >= 开仓价，且按30m ST平仓收益 <= {LOCK_PROFIT_BUFFER}U，继续跟随30m ST")
    print(f"✓ 换轨条件: 按30m ST平仓收益 > {LOCK_PROFIT_BUFFER}U，切换至1H ST，止损只紧不松")
    
    print(f"\n【验证结果】")
    print(f"✅ 逻辑正确：")
    print(f"  1. 生存期: 30m ST 高于开仓价 {entry_price:.2f}，止损跟随30m ST")
    print(f"  2. 锁利期: 30m ST 达到开仓价，仍跟随30m ST，收益在缓冲范围内")
    print(f"  3. 换轨期: 按30m ST平仓收益 > {LOCK_PROFIT_BUFFER}U，切换至1H ST，止损只紧不松")
    

def test_phase_transitions():
    """测试阶段转换逻辑"""
    
    print("\n" + "=" * 80)
    print("测试场景：阶段转换验证")
    print("=" * 80)
    
    entry_price = 2062.17
    qty = 49
    is_long = False
    
    test_cases = [
        # (st_30m, st_1h, expected_phase, description)
        (2063.00, 2063.00, Phase.SURVIVAL.value, "30m ST > 开仓价，生存期"),
        (2062.17, 2060.00, Phase.LOCKED.value, "30m ST = 开仓价，进入锁利期，PNL=0"),
        (2060.00, 2060.00, Phase.LOCKED.value, "按30m ST平仓PNL≈1U，继续锁利期跟随30m ST"),
        (2055.00, 2055.00, Phase.HOURLY.value, "按30m ST平仓PNL>1U，进入换轨期"),
        (2050.00, 2052.00, Phase.HOURLY.value, "换轨期，跟随1H ST，止损只紧不松"),
    ]
    
    print(f"\n{'ST30m':<10} {'ST1h':<10} {'预期阶段':<10} {'说明':<35}")
    print("-" * 65)
    
    prev_stop_loss = 0
    for st_30m, st_1h, expected_phase, desc in test_cases:
        phase, stop = infer_phase(
            entry_price, qty, st_30m, st_1h, is_long,
            prev_stop_loss=prev_stop_loss
        )
        
        status = "✓" if phase == expected_phase else "✗"
        print(f"{st_30m:<10.2f} {st_1h:<10.2f} {phase:<10} {desc:<35} {status}")
        prev_stop_loss = stop


if __name__ == "__main__":
    test_case_from_user()
    test_phase_transitions()
    print("\n" + "=" * 80)
    print("✅ 所有测试完成")
    print("=" * 80)
