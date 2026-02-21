#!/usr/bin/env python3
"""
测试K线完整性 - 确认Gate.io API返回的最后一根K线是否已完成
"""

import os
import time
from datetime import datetime, timezone, timedelta
from gate_client import GateClient
from config import GATE_API_KEY, GATE_API_SECRET, CONTRACT

def test_kline_completion():
    """
    测试逻辑：
    在整点或整30分的边界附近运行，观察API返回的K线时间戳
    - 如果最后一根K线时间戳 = 当前时间之前的完整周期 → API返回已完成K线
    - 如果最后一根K线时间戳 = 当前时间所在周期 → API可能返回进行中的K线
    """
    client = GateClient(GATE_API_KEY, GATE_API_SECRET, debug=True)
    
    now = datetime.now(timezone.utc)
    print(f"\n🕐 测试时间: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)
    
    # 获取30m K线
    print("\n【测试30m K线】")
    df_30m = client.get_candlesticks(CONTRACT, "30m", 5)
    print("\n最近5根30分钟K线:")
    for i, (idx, row) in enumerate(df_30m.iterrows()):
        time_diff = (now - idx).total_seconds() / 60
        status = "📊 当前进行中" if time_diff < 30 else "✅ 已完成"
        print(f"  {i}: {idx.strftime('%Y-%m-%d %H:%M')} (距现在{time_diff:.1f}分钟) {status}")
    
    # 获取1h K线
    print("\n【测试1h K线】")
    df_1h = client.get_candlesticks(CONTRACT, "1h", 5)
    print("\n最近5根1小时K线:")
    for i, (idx, row) in enumerate(df_1h.iterrows()):
        time_diff = (now - idx).total_seconds() / 60
        status = "📊 当前进行中" if time_diff < 60 else "✅ 已完成"
        print(f"  {i}: {idx.strftime('%Y-%m-%d %H:%M')} (距现在{time_diff:.1f}分钟) {status}")
    
    print("\n【诊断结论】")
    print("✅ 如果最后一根K线距现在 < 周期时间 → iloc[-1]是进行中的K线")
    print("   应使用 iloc[-2] 作为「最近一根完整K线」")
    print("❌ 如果最后一根K线距现在 ≥ 周期时间 → iloc[-1]已完成")
    print("   应改用 iloc[-1] 作为「最近一根完整K线」")

if __name__ == "__main__":
    test_kline_completion()
