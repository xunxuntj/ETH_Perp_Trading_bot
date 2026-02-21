"""
TradingView风格的EMA初始化 - 使用SMA的第一个EMA初始化
"""

import pandas as pd
import numpy as np
import sys

sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient


def calculate_ema_tradingview(series: pd.Series, period: int = 200):
    """
    TradingView的EMA计算方式
    第一个EMA值 = 前period个值的SMA
    """
    ema = np.zeros(len(series))
    alpha = 2.0 / (period + 1)
    
    # 第一个EMA值用SMA初始化
    ema[period - 1] = series.iloc[:period].mean()
    
    # 之后用标准EMA递推
    for i in range(period, len(series)):
        ema[i] = alpha * series.iloc[i] + (1 - alpha) * ema[i - 1]
    
    # 前面的值用NaN
    for i in range(period - 1):
        ema[i] = np.nan
    
    return pd.Series(ema, index=series.index)


def calculate_dema_tradingview(series: pd.Series, period: int = 200):
    """
    TradingView方式的DEMA
    """
    ema1 = calculate_ema_tradingview(series, period)
    # 只对有效的EMA1值计算EMA2
    ema2_values = []
    ema2_valid_indices = []
    
    j = 0
    for i in range(len(ema1)):
        if not pd.isna(ema1.iloc[i]):
            ema2_valid_indices.append(i)
            ema2_values.append(ema1.iloc[i])
    
    if len(ema2_values) < period:
        # 数据不足
        return pd.Series(np.full(len(series), np.nan), index=series.index), ema1, None
    
    ema2 = calculate_ema_tradingview(pd.Series(ema2_values), period)
    
    # 映射回原索引
    ema2_full = pd.Series(np.full(len(series), np.nan), index=series.index)
    for i, idx in enumerate(ema2_valid_indices):
        if i < len(ema2):
            ema2_full.iloc[idx] = ema2.iloc[i]
    
    dema = 2 * ema1 - ema2_full
    
    return dema, ema1, ema2_full


def comprehensive_comparison():
    """
    全面对比所有方式
    """
    print("\n" + "=" * 100)
    print("TradingView方式DEMA计算")
    print("=" * 100)
    
    client = GateClient()
    
    # 获取更多K线数据
    df_1h = client.get_candlesticks("ETH_USDT", "1h", 300)
    
    print(f"\n【K线数据】")
    print(f"  共{len(df_1h)}根K线")
    print(f"  时间范围: {df_1h.index[0]} 到 {df_1h.index[-1]}")
    
    # 计算方式1: 当前实现
    from indicators import calculate_dema
    dema_current = calculate_dema(df_1h['close'], 200)
    
    # 计算方式2: TradingView方式
    dema_tv, ema1_tv, ema2_tv = calculate_dema_tradingview(df_1h['close'], 200)
    
    # 计算方式3: 带更多历史的（如果数据足够）
    print(f"\n【三种方式对比】")
    print(f"{'索引':<6} {'收盘':<10} {'当前实现':<15} {'TV方式':<15} {'差异':<10}")
    print("-" * 70)
    
    for i in range(-20, 0):
        idx = len(df_1h) + i
        close = df_1h['close'].iloc[i]
        current = dema_current.iloc[i]
        tv = dema_tv.iloc[i]
        
        if pd.isna(tv):
            tv_str = "NaN"
            diff_str = "N/A"
        else:
            tv_str = f"{tv:.2f}"
            diff = abs(current - tv)
            diff_str = f"{diff:.2f}"
        
        print(f"{idx:<6} {close:<10.2f} {current:<15.2f} {tv_str:<15} {diff_str:<10}")
    
    print(f"\n【用于交易的值 (iloc[-2])】")
    print(f"  当前实现:     {dema_current.iloc[-2]:.2f}")
    print(f"  TradingView:  {dema_tv.iloc[-2]:.2f if not pd.isna(dema_tv.iloc[-2]) else 'NaN'}")
    
    if not pd.isna(dema_tv.iloc[-2]):
        print(f"  差异:         {abs(dema_current.iloc[-2] - dema_tv.iloc[-2]):.2f}")
    
    # 显示有效DEMA的位置
    valid_indices = [i for i in range(len(dema_tv)) if not pd.isna(dema_tv.iloc[i])]
    if valid_indices:
        print(f"\n【计算说明】")
        print(f"  TradingView方式的EMA/DEMA:")
        print(f"    - 前{200-1}根K线: 无法计算（需要SMA初始化）")
        print(f"    - 第{valid_indices[0]}根开始有效")
        print(f"    - 最少需要第一EMA有效后再度过一个period才能计算DEMA")
    
    return {
        'current': dema_current,
        'tv': dema_tv,
        'df': df_1h,
        'ema1_tv': ema1_tv,
    }


def analyze_historical_data():
    """
    分析使用更多历史数据的效果
    """
    print(f"\n\n" + "=" * 100)
    print("历史数据影响分析")
    print("=" * 100)
    
    client = GateClient()
    
    # 获取历史数据
    data_sizes = [100, 150, 200, 300]
    results = {}
    
    print(f"\n【不同历史数据量的DEMA值】")
    print(f"{'数据量':<8} {'最后K线':<25} {'DEMA值':<12} {'与300的差异':<15}")
    print("-" * 70)
    
    for size in data_sizes:
        try:
            df = client.get_candlesticks("ETH_USDT", "1h", size)
            from indicators import calculate_dema
            dema = calculate_dema(df['close'], 200)
            value = dema.iloc[-2]
            results[size] = value
            
            print(f"{size:<8} {str(df.index[-2]):<25} {value:<12.2f}", end="")
            
            if size == 300:
                print(f"{'基准':<15}")
            else:
                diff = abs(value - results.get(300, value))
                print(f"{diff:<15.2f}")
        except Exception as e:
            print(f"{size:<8} 获取失败: {str(e)[:40]}")
    
    print(f"\n【结论】")
    print(f"  数据量300时的DEMA: {results.get(300, '?'):.2f}")
    print(f"  TradingView值:    1925.64")
    print(f"  差异:             {abs(results.get(300, 0) - 1925.64):.2f}")


if __name__ == '__main__':
    try:
        results = comprehensive_comparison()
        analyze_historical_data()
        
        print(f"\n\n【关键发现】")
        print(f"""
TradingView的DEMA计算步骤：
1. 计算EMA1: 前200个值的SMA作为初始值，然后用EMA递推
2. 计算EMA2: 在EMA1有效值上重复步骤1
3. DEMA = 2 * EMA1 - EMA2

这意味着：
- 需要至少 200 + 200 = 400根K线才能得到第一个有效的DEMA值
- 当前获取300根K线可能不够

建议：
1. 如果改用TradingView方式后值仍然不对
2. 尝试获取500+根K线
3. 或者考虑K线本身是否完整（是否有缺失）
""")
        
    except Exception as e:
        print(f"分析失败: {e}")
        import traceback
        traceback.print_exc()
