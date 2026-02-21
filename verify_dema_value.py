"""
DEMA差异排查指南

用途: 当发现本地DEMA值与TradingView不一致时，按步骤排查问题
"""

import pandas as pd
import sys
from datetime import datetime

sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
from indicators import calculate_dema, calculate_dema_debug
from config import DEMA_PERIOD


def verify_dema_value(timeframe="1h", check_time=None):
    """
    验证当前DEMA值
    
    Args:
        timeframe: '30m' 或 '1h'
        check_time: 要检查的时间（可选）
    """
    print("\n" + "=" * 100)
    print(f"DEMA差异排查工具 - {timeframe}线")
    print("=" * 100)
    
    client = GateClient()
    
    # 获取300根K线
    df = client.get_candlesticks("ETH_USDT", timeframe, 300)
    
    # 计算DEMA
    dema = calculate_dema(df['close'], DEMA_PERIOD)
    debug_info = calculate_dema_debug(df, DEMA_PERIOD)
    
    print(f"\n【1. K线数据验证】")
    print(f"  获取K线数: {len(df)}")
    print(f"  收盘价范围: {df['close'].min():.2f} - {df['close'].max():.2f}")
    print(f"  收盘价均值: {df['close'].mean():.2f}")
    print(f"  K线时间范围: {df.index[0]} 到 {df.index[-1]}")
    
    print(f"\n【2. DEMA计算验证 (Period={DEMA_PERIOD})】")
    print(f"  EMA初始值检查:")
    print(f"    EMA1[0] = {debug_info['ema1'].iloc[0]:.2f} (第一收盘价: {df['close'].iloc[0]:.2f})")
    print(f"    EMA2[0] = {debug_info['ema2'].iloc[0]:.2f}")
    print(f"    DEMA[0] = {dema.iloc[0]:.2f}")
    
    print(f"\n【3. 用于交易的值 (iloc[-2] = 上一根完整K线)】")
    print(f"  K线时间: {df.index[-2]}")
    print(f"  收盘价: {debug_info['last_close']:.2f}")
    print(f"  EMA1: {debug_info['last_ema1']:.2f}")
    print(f"  EMA2: {debug_info['last_ema2']:.2f}")
    print(f"  DEMA: {debug_info['last_dema']:.2f} ✓ ← 这是你看到的值")
    
    print(f"\n【4. 最近20根K线的DEMA】")
    print(f"{'Index':<7} {'时间':<25} {'Close':<12} {'DEMA':<12} {'差值':<12}")
    print("-" * 80)
    
    for i in range(-20, 0):
        idx = len(df) + i
        close = df['close'].iloc[i]
        dema_val = dema.iloc[i]
        diff = close - dema_val
        ts = str(df.index[idx])[:19]
        print(f"{idx:<7} {ts:<25} {close:<12.2f} {dema_val:<12.2f} {diff:<12.2f}")
    
    print(f"\n【5. 与TradingView对比步骤】")
    print(f"""
步骤1: 在TradingView中检查与此相同K线时间的DEMA值
       - 要检查的K线时间: {df.index[-2]}
       - 该K线的收盘价: {debug_info['last_close']:.2f}
       - 本地计算的DEMA: {debug_info['last_dema']:.2f}

步骤2: 在TradingView图表中设置DEMA指标
       - Script: 使用标准Double EMA
       - Length: 200
       - Source: Close
       - Timeframe: {timeframe}
       - 等待K线完全闭合

步骤3: 对比两个DEMA值
       - 如果相同: ✓ 数据源一致，没有问题
       - 如果不同: 检查以下几点
         a) K线时间戳是否对齐？
         b) 收盘价是否相同？
         c) 是用的是上一根完整K线（iloc[-2]）吗？
""")
    
    # 检查当前K线是否真的完整
    print(f"\n【6. K线完整性检查】")
    current_hour = datetime.now().hour
    last_kline_hour = df.index[-1].hour
    
    print(f"  当前UTC小时: {current_hour}")
    print(f"  最新K线时间小时: {last_kline_hour}")
    
    if current_hour == last_kline_hour:
        print(f"  ⚠️  当前K线可能仍在形成中！")
        print(f"      建议使用 iloc[-2] (上一根完整K线)")
        print(f"      该K线时间: {df.index[-2]}, DEMA: {debug_info['last_dema']:.2f}")
    else:
        print(f"  ✓ 最新K线已完整闭合")
    
    return {
        'df': df,
        'dema': dema,
        'debug_info': debug_info
    }


def compare_with_manual_values(local_dema, tv_dema, tolerance=0.5):
    """
    对比本地DEMA和TradingView DEMA值
    """
    print(f"\n【对比结果】")
    print(f"  本地DEMA: {local_dema:.2f}")
    print(f"  TradingView DEMA: {tv_dema:.2f}")
    print(f"  差异: {abs(local_dema - tv_dema):.2f}")
    print(f"  差异百分比: {abs(local_dema - tv_dema) / tv_dema * 100:.2f}%")
    
    if abs(local_dema - tv_dema) < tolerance:
        print(f"  ✓ 差异在可接受范围内 (<{tolerance})")
        return True
    else:
        print(f"  ✗ 差异超出范围 (>{tolerance})")
        print(f"\n    可能原因:")
        print(f"    1. K线数据源不同")
        print(f"    2. K线时间戳不对齐")
        print(f"    3. 计算周期不对齐（检查是否真的使用了200周期）")
        print(f"    4. 当前K线仍在形成中（未使用iloc[-2]）")
        return False


if __name__ == '__main__':
    import os
    
    os.environ['GATE_DEBUG'] = '0'
    
    # 检查1H DEMA
    results_1h = verify_dema_value('1h')
    
    print(f"\n\n" + "=" * 100)
    print("【手动对比说明】")
    print("=" * 100)
    print("""
如果需要与TradingView的DEMA值进行对比:

1. 在TradingView上查看 1h DEMA 的值（K线完全闭合后）
2. 记下该值
3. 运行此脚本，得到本地计算的DEMA值
4. 对比两个值是否接近（允许误差<1%）

例如:
  - 本地: 1952.81
  - TradingView: 1952.80
  - 差异: 0.01 (完全一致) ✓

如果差异>1%, 表示问题可能在于:
  - 数据源不同（不同交易所、不同合约、不同K线周期）
  - 时间同步问题（时区差异、K线未完全闭合）
  - 初始化方式不同
""")
