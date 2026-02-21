"""
深层次DEMA差异诊断 - 检查EMA初始化和K线数据
"""

import pandas as pd
import numpy as np
import sys

sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
from indicators import calculate_dema


def calculate_ema_with_sma_init(series: pd.Series, period: int = 200):
    """
    使用SMA初始化的EMA（某些平台使用此方式）
    前 period 个值用SMA，之后用EMA
    """
    ema = pd.Series(index=series.index, dtype=float)
    
    # 前100个值用简单平均初始化
    if len(series) >= period:
        ema.iloc[period - 1] = series.iloc[:period].mean()
    else:
        ema.iloc[0] = series.iloc[0]
        return ema
    
    # 之后用标准EMA
    alpha = 2.0 / (period + 1)
    for i in range(period, len(series)):
        ema.iloc[i] = alpha * series.iloc[i] + (1 - alpha) * ema.iloc[i - 1]
    
    return ema


def calculate_dema_with_sma_init(series: pd.Series, period: int = 200):
    """
    使用SMA初始化的DEMA
    """
    ema1 = calculate_ema_with_sma_init(series, period)
    ema2 = calculate_ema_with_sma_init(ema1, period)
    dema = 2 * ema1 - ema2
    return dema, ema1, ema2


def analyze_kline_differences():
    """
    分析K线数据和计算差异
    """
    print("\n" + "=" * 100)
    print("深层次DEMA差异诊断")
    print("=" * 100)
    
    client = GateClient()
    
    # 获取大量K线数据（最多请求）
    df_1h = client.get_candlesticks("ETH_USDT", "1h", 300)
    
    print(f"\n【K线数据基本信息】")
    print(f"  获取K线数: {len(df_1h)}")
    print(f"  收盘价范围: {df_1h['close'].min():.2f} - {df_1h['close'].max():.2f}")
    print(f"  第一根K线: {df_1h.index[0]} close={df_1h['close'].iloc[0]:.2f}")
    print(f"  最后一根K线: {df_1h.index[-1]} close={df_1h['close'].iloc[-1]:.2f}")
    
    # 计算不同方式的DEMA
    print(f"\n【DEMA计算对比】")
    
    # 方式1: 当前实现 (pandas ewm adjust=False)
    dema_current = calculate_dema(df_1h['close'], 200)
    
    # 方式2: SMA初始化的DEMA
    dema_sma, ema1_sma, ema2_sma = calculate_dema_with_sma_init(df_1h['close'], 200)
    
    # 方式3: 完全的SMA开始（前200个用SMA平均）
    ema1_current = df_1h['close'].ewm(span=200, adjust=False).mean()
    ema2_current = ema1_current.ewm(span=200, adjust=False).mean()
    
    print(f"\n【最后10根K线的对比】")
    print(f"{'Idx':<6} {'Close':<10} {'当前实现':<15} {'SMA初始':<15} {'差异':<10}")
    print("-" * 70)
    
    for i in range(-10, 0):
        idx = len(df_1h) + i
        c = dema_current.iloc[i]
        s = dema_sma.iloc[i]
        diff = abs(c - s)
        close = df_1h['close'].iloc[i]
        print(f"{idx:<6} {close:<10.2f} {c:<15.2f} {s:<15.2f} {diff:<10.2f}")
    
    print(f"\n【用于交易的值 (iloc[-2])】")
    print(f"  当前实现:   {dema_current.iloc[-2]:.2f}")
    print(f"  SMA初始:    {dema_sma.iloc[-2]:.2f}")
    print(f"  差异:       {abs(dema_current.iloc[-2] - dema_sma.iloc[-2]):.2f}")
    
    # 分析EMA初始值
    print(f"\n【EMA初始值分析】")
    print(f"  收盘价[0]: {df_1h['close'].iloc[0]:.2f}")
    print(f"  EMA1[0] (当前): {ema1_current.iloc[0]:.2f} (应该等于收盘价)")
    print(f"  EMA1[0] (SMA): {ema1_sma.iloc[0]:.2f} (前200根的平均值)")
    
    if len(df_1h) >= 200:
        avg_first_200 = df_1h['close'].iloc[:200].mean()
        print(f"  前200根收盘的平均值: {avg_first_200:.2f}")
    
    # 查看收敛情况
    print(f"\n【EMA值变化趋势（最后15根K线）】")
    print(f"{'Idx':<6} {'Close':<10} {'EMA1-当前':<15} {'EMA1-SMA':<15} {'收敛差异':<15}")
    print("-" * 80)
    
    for i in range(-15, 0):
        idx = len(df_1h) + i
        close = df_1h['close'].iloc[i]
        e1c = ema1_current.iloc[i]
        e1s = ema1_sma.iloc[i]
        diff = abs(e1c - e1s)
        print(f"{idx:<6} {close:<10.2f} {e1c:<15.2f} {e1s:<15.2f} {diff:<15.2f}")
    
    print(f"\n【诊断分析】")
    print(f"""
可能的差异来源：

1. 初始化方式不同:
   - 当前实现: EMA第一个值 = 第一个收盘价
   - TradingView可能用: SMA初始化
   
2. 数据样本大小:
   - 当前: 300根K线
   - TradingView: 可能用了更多历史数据
   
3. 收敛性:
   - 初始值差异会随着K线增加而收敛
   - 但如果历史数据不同，可能永远无法对齐
   
4. 关键发现:
   - 如果SMA初始的DEMA值与TradingView接近
   - 说明初始化方式是关键差异
   - 需要改改为SMA初始化的EMA
""")
    
    return {
        'current': dema_current,
        'sma_init': dema_sma,
        'df': df_1h,
        'ema1_current': ema1_current,
        'ema1_sma': ema1_sma,
    }


def check_different_periods():
    """
    检查是否实际使用的是不同周期
    """
    print(f"\n" + "=" * 100)
    print("周期对齐检查")
    print("=" * 100)
    
    client = GateClient()
    df_1h = client.get_candlesticks("ETH_USDT", "1h", 300)
    
    periods_to_check = [100, 150, 200, 250, 300]
    
    print(f"\n【不同周期下的DEMA值】")
    print(f"{'周期':<6} {'DEMA-Current':<15} {'与200周期的差异':<20} {'百分比':<10}")
    print("-" * 60)
    
    dema_200 = calculate_dema(df_1h['close'], 200)
    base_value = dema_200.iloc[-2]
    
    for period in periods_to_check:
        try:
            dema = calculate_dema(df_1h['close'], period)
            value = dema.iloc[-2]
            diff = abs(value - base_value)
            pct = (diff / base_value) * 100 if base_value != 0 else 0
            print(f"{period:<6} {value:<15.2f} {diff:<20.2f} {pct:<10.2f}%")
        except:
            pass
    
    print(f"\n基准值 (200周期): {base_value:.2f}")
    print(f"TradingView值: 1925.64")
    print(f"差距: {abs(base_value - 1925.64):.2f} ({abs(base_value - 1925.64) / 1925.64 * 100:.2f}%)")


if __name__ == '__main__':
    try:
        results = analyze_kline_differences()
        check_different_periods()
        
        print(f"\n\n【建议】")
        print(f"""
如果SMA初始化的DEMA值与TradingView接近:
  → 改为使用SMA初始化的EMA计算
  → 修改 calculate_dema() 函数

后续步骤:
1. 对比 "当前实现" 和 "SMA初始" 的差异
2. 如果SMA初始更接近TradingView，考虑切换
3. 否则，问题可能在于完整的K线历史不同
""")
        
    except Exception as e:
        print(f"诊断失败: {e}")
        import traceback
        traceback.print_exc()
