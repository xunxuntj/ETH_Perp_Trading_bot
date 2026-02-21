#!/usr/bin/env python3
"""
深度诊断脚本：检查信号判断的时序一致性

这个脚本会：
1. 获取最新的K线数据
2. 计算指标（ST、DEMA）
3. 对比信号源和实际入场价格的时间差异
4. 显示所有关键数值，帮你追踪问题
"""

import os
import sys
from datetime import datetime, timezone
import pandas as pd

from config import GATE_API_KEY, GATE_API_SECRET, CONTRACT
from gate_client import GateClient
from indicators import calculate_supertrend, calculate_dema
from strategy import calculate_position_size


def diagnose_signal_timing():
    """诊断信号和入场价格的时序问题"""
    
    client = GateClient(GATE_API_KEY, GATE_API_SECRET, debug=True)
    
    now = datetime.now(timezone.utc)
    print(f"\n{'='*70}")
    print(f"🔍 信号时序一致性诊断")
    print(f"时间: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*70}\n")
    
    # 获取数据
    print("📥 获取行情数据...")
    df_30m = client.get_candlesticks(CONTRACT, "30m", 10)
    df_1h = client.get_candlesticks(CONTRACT, "1h", 10)
    
    # 计算指标
    st_30m = calculate_supertrend(df_30m)
    st_1h = calculate_supertrend(df_1h)
    dema_1h = calculate_dema(df_1h['close'])
    
    print("\n" + "="*70)
    print("【30分钟K线分析】")
    print("="*70)
    
    # 显示最后4根30m K线
    for i in range(-4, 0):
        idx = df_30m.index[i]
        close = df_30m['close'].iloc[i]
        st_val = st_30m['supertrend'].iloc[i]
        st_dir = "🟢UP" if st_30m['direction'].iloc[i] == 1 else "🔴DN"
        time_ago = (now - idx).total_seconds() / 60
        
        marker = ""
        if i == -1:
            marker = "  ← iloc[-1] (当前进行中的K?)  ⚠️"
        elif i == -2:
            marker = "  ← iloc[-2] (当前代码用这个)  📍"
        
        print(f"  [{i}] {idx.strftime('%H:%M')} | Close: {close:8.2f} | ST: {st_val:8.2f} {st_dir} | {time_ago:5.1f}分钟前{marker}")
    
    print("\n" + "="*70)
    print("【1小时K线分析】")
    print("="*70)
    
    # 显示最后4根1h K线
    for i in range(-4, 0):
        idx = df_1h.index[i]
        close = df_1h['close'].iloc[i]
        dema = dema_1h.iloc[i]
        st_val = st_1h['supertrend'].iloc[i]
        st_dir = "🟢UP" if st_1h['direction'].iloc[i] == 1 else "🔴DN"
        time_ago = (now - idx).total_seconds() / 60
        
        # 比较收盘价和DEMA
        pos = ">" if close > dema else "<"
        
        marker = ""
        if i == -1:
            marker = "  ← iloc[-1]  ⚠️"
        elif i == -2:
            marker = "  ← iloc[-2] (当前代码用这个)  📍"
        
        print(f"  [{i}] {idx.strftime('%H:%M')} | Close: {close:8.2f} | DEMA: {dema:8.2f} {pos} | ST: {st_val:8.2f} {st_dir}{marker}")
    
    print("\n" + "="*70)
    print("【关键问题诊断】")
    print("="*70)
    
    # 分析 iloc[-1] 的情况
    last_30m_time = df_30m.index[-1]
    last_30m_close = df_30m['close'].iloc[-1]
    time_since_30m = (now - last_30m_time).total_seconds() / 60
    
    print(f"\n🕐 最后一条30分钟K线:")
    print(f"   时间: {last_30m_time.strftime('%H:%M')}")
    print(f"   收盘价: {last_30m_close:.2f}")
    print(f"   距现在: {time_since_30m:.1f} 分钟前")
    
    if time_since_30m < 30:
        print(f"   ⚠️  结论: 这根K线还在进行中! iloc[-1]是未完成的K线")
        print(f"       → 当前代码用 iloc[-2] 是对的")
        print(f"       → 但入场价格用 iloc[-1] 会有问题!")
    else:
        print(f"   ✅ 结论: 这根K线已完成! iloc[-1]是最新完整K线")
        print(f"       → 当前代码用 iloc[-2] 可能会导致滞后!")
        print(f"       → 应改为用 iloc[-1]")
    
    print("\n" + "="*70)
    print("【信号判断检查】")
    print("="*70)
    
    # 检查信号源
    last_1h_close = df_1h['close'].iloc[-2]
    last_1h_dema = dema_1h.iloc[-2]
    last_1h_dir = int(st_1h['direction'].iloc[-2])
    last_30m_dir = int(st_30m['direction'].iloc[-2])
    last_30m_st = st_30m['supertrend'].iloc[-2]
    
    # 但入场价用的是
    current_price = df_30m['close'].iloc[-1]
    
    print(f"\n【当前代码逻辑】:")
    print(f"  信号判断用:")
    print(f"    • 1H ST方向: {last_1h_dir:+d} (iloc[-2])" + (" 🟢" if last_1h_dir == 1 else " 🔴"))
    print(f"    • 1H Close: {last_1h_close:.2f} vs DEMA: {last_1h_dema:.2f} (iloc[-2])")
    print(f"    • 30m ST方向: {last_30m_dir:+d} (iloc[-2])" + (" 🟢" if last_30m_dir == 1 else " 🔴"))
    print(f"    • 30m ST值: {last_30m_st:.2f} (iloc[-2], 用作止损)")
    
    print(f"\n  但入场时用:")
    print(f"    • 当前价格: {current_price:.2f} (iloc[-1], 可能未完成K线)")
    
    # 计算这会对仓位有多大影响
    print(f"\n【时序不一致的影响】:")
    
    # 假设一个风险场景
    risk_amount = 100  # 假设
    pos_info = calculate_position_size(risk_amount, current_price, last_30m_st)
    
    print(f"  假设风险金额: {risk_amount}U")
    print(f"  入场价 {current_price:.2f} 计算出:")
    print(f"    • 止损距离: {pos_info['sl_distance']:.2f}点")
    print(f"    • 建议张数: {pos_info['qty']}张")
    print(f"    • 仓位: {pos_info['position_eth']:.3f} ETH")
    print(f"    • 实际风险: {pos_info['actual_risk']:.2f}U")
    
    # 比较如果用信号源的价格会怎样
    signal_price = last_1h_close
    pos_info_signal = calculate_position_size(risk_amount, signal_price, last_30m_st)
    
    print(f"\n  如果用信号源价格 {signal_price:.2f} 计算:")
    print(f"    • 止损距离: {pos_info_signal['sl_distance']:.2f}点")
    print(f"    • 建议张数: {pos_info_signal['qty']}张")
    print(f"    • 仓位: {pos_info_signal['position_eth']:.3f} ETH")
    
    if pos_info['qty'] != pos_info_signal['qty']:
        print(f"\n  ⚠️  问题: 张数不一致! 相差 {abs(pos_info['qty'] - pos_info_signal['qty'])} 张")
    
    print(f"\n{'='*70}")
    print("【建议】")
    print("="*70)
    print("""
1. 运行此脚本多次，在不同时间点运行（特别是K线整点时刻）
2. 根据"距现在"的分钟数判断K线是否进行中
3. 如果 iloc[-1] 的"距现在" < 周期时间 → 需要修复时序问题
4. 修复方案:
   a) 统一用 iloc[-2] (如果API返回进行中的K)
      - current_price = df_30m['close'].iloc[-2] ← 改这里
      - 这样信号源和入场价就一致了
   
   b) 或者确认API只返回已完成K，全部改成 iloc[-1]
      - 所有地方都改成 iloc[-1]
""")
    print("="*70)


if __name__ == "__main__":
    diagnose_signal_timing()
