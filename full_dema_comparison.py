"""
获取足够历史数据的DEMA计算对比
"""

import pandas as pd
import numpy as np
import sys

sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
from indicators import calculate_dema


def calculate_ema_with_sma_init(series: pd.Series, period: int = 200):
    """
    使用SMA初始化的EMA（TradingView方式）
    """
    if len(series) < period:
        return pd.Series(np.full(len(series), np.nan), index=series.index)
    
    ema = np.full(len(series), np.nan)
    alpha = 2.0 / (period + 1)
    
    # 第一个有效值用SMA初始化
    ema[period - 1] = series.iloc[:period].mean()
    
    # 之后用标准EMA递推
    for i in range(period, len(series)):
        ema[i] = alpha * series.iloc[i] + (1 - alpha) * ema[i - 1]
    
    return pd.Series(ema, index=series.index)


def calculate_dema_with_sma_init(series: pd.Series, period: int = 200):
    """
    使用SMA初始化的DEMA（TradingView方式）
    """
    ema1 = calculate_ema_with_sma_init(series, period)
    
    # ema2只对ema1有效的部分计算
    ema1_valid = ema1.dropna()
    if len(ema1_valid) < period:
        return pd.Series(np.full(len(series), np.nan), index=series.index)
    
    ema2_array = np.full(len(series), np.nan)
    alpha = 2.0 / (period + 1)
    
    # ema2的第一个值（在ema1有效的部分中）
    ema2_values = ema1_valid.values
    ema2_array[ema1.notna().argmax() + period - 1] = ema2_values[:period].mean()
    
    # 继续递推
    j = ema1.notna().argmax()  # ema1开始有效的位置
    last_valid_ema2 = ema2_array[ema1.notna().argmax() + period - 1]
    
    for i in range(ema1.notna().argmax() + period, len(series)):
        if not pd.isna(ema1.iloc[i]):
            ema2_array[i] = alpha * ema1.iloc[i] + (1 - alpha) * last_valid_ema2
            last_valid_ema2 = ema2_array[i]
    
    ema2 = pd.Series(ema2_array, index=series.index)
    dema = 2 * ema1 - ema2
    
    return dema, ema1, ema2


def compare_multiple_sizes():
    """
    获取不同大小的数据并对比
    """
    print("\n" + "=" * 120)
    print("DEMA计算对比 - 不同历史数据量")
    print("=" * 120)
    
    client = GateClient()
    
    # 获取最多的K线（500根）
    df_500 = client.get_candlesticks("ETH_USDT", "1h", 500)
    
    print(f"\n【获取的K线数据】")
    print(f"  共{len(df_500)}根K线")
    print(f"  时间范围: {df_500.index[0]} 到 {df_500.index[-1]}")
    print(f"  收盘价范围: {df_500['close'].min():.2f} - {df_500['close'].max():.2f}")
    
    # 计算两种方式
    print(f"\n【DEMA计算方式对比】")
    
    # 方式1: 当前实现 (pandas ewm adjust=False)
    dema_current = calculate_dema(df_500['close'], 200)
    
    # 方式2: SMA初始化（TradingView风格）
    dema_sma_init, ema1_sma, ema2_sma = calculate_dema_with_sma_init(df_500['close'], 200)
    
    print(f"\n【最后20根K线对比】")
    print(f"{'Idx':<6} {'时间':<20} {'收盘':<10} {'当前':<15} {'SMA初始':<15} {'差异':<12}")
    print("-" * 90)
    
    for i in range(-20, 0):
        idx = len(df_500) + i
        ts = str(df_500.index[i])[:16]
        close = df_500['close'].iloc[i]
        current = dema_current.iloc[i]
        sma = dema_sma_init.iloc[i]
        
        if pd.isna(sma):
            sma_str = "N/A"
            diff_str = "N/A"
        else:
            sma_str = f"{sma:.2f}"
            diff = abs(current - sma)
            diff_str = f"{diff:.2f}"
        
        print(f"{idx:<6} {ts:<20} {close:<10.2f} {current:<15.2f} {sma_str:<15} {diff_str:<12}")
    
    print(f"\n【关键数据】")
    print(f"  用于交易的K线: iloc[-2]")
    print(f"  时间: {df_500.index[-2]}")
    print(f"  收盘: {df_500['close'].iloc[-2]:.2f}")
    print(f"  当前实现 DEMA: {dema_current.iloc[-2]:.2f}")
    
    if not pd.isna(dema_sma_init.iloc[-2]):
        print(f"  SMA初始 DEMA: {dema_sma_init.iloc[-2]:.2f}")
        print(f"  差异: {abs(dema_current.iloc[-2] - dema_sma_init.iloc[-2]):.2f}")
    else:
        print(f"  SMA初始 DEMA: N/A (数据不足)")
    
    print(f"  TradingView: 1925.64")
    print(f"  当前实现 vs TV: {abs(dema_current.iloc[-2] - 1925.64):.2f}")
    
    # 显示SMA初始什么时候开始有效
    if not dema_sma_init.isna().all():
        first_valid_idx = dema_sma_init.notna().argmax()
        print(f"\n【SMA初始化说明】")
        print(f"  EMA1第一个有效值: 位置{200-1} (需要200根K线的SMA)")
        print(f"  DEMA第一个有效值: 位置{first_valid_idx} (需要EMA2也有效)")
        print(f"  有效DEMA值数: {dema_sma_init.notna().sum()}")
        
        # 显示最后有效DEMA值的上下文
        print(f"\n【最后5个有效DEMA值】")
        valid_indices = dema_sma_init[dema_sma_init.notna()].index
        if len(valid_indices) > 0:
            for idx in valid_indices[-5:]:
                i = df_500.index.get_loc(idx)
                print(f"  位置{i}: {df_500['close'].iloc[i]:.2f} → DEMA {dema_sma_init.iloc[i]:.2f}")
    
    # 对比所有有效值
    both_valid = (dema_current.notna()) & (dema_sma_init.notna())
    if both_valid.any():
        diff = (dema_current[both_valid] - dema_sma_init[both_valid]).abs()
        print(f"\n【两种方式的差异统计】")
        print(f"  最大差异: {diff.max():.2f}")
        print(f"  平均差异: {diff.mean():.2f}")
        print(f"  最小差异: {diff.min():.2f}")


if __name__ == '__main__':
    try:
        compare_multiple_sizes()
        
        print(f"\n\n【推荐行动】")
        print(f"""
关键发现：
1. 300根K线下：DEMA ≈ 1951
2. SMA初始化可能需要400+根K线才能有效
3. TradingView的1925.64可能基于更多历史数据或不同的初始化方式

下一步：
1. 如果SMA初始的值接近TradingView，考虑改为SMA初始化
2. 如果仍然差距大，问题可能在于：
   - K线数据源本身不同
   - 时间戳对齐问题
   - 或TradingView使用了不同的方法

建议先对比原始K线数据是否一致，再决定修改DEMA计算方式。
""")
        
    except Exception as e:
        print(f"分析失败: {e}")
        import traceback
        traceback.print_exc()
