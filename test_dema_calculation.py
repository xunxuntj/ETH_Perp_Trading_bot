"""
诊断DEMA计算差异 - 对比TradingView和pandas实现
"""

import pandas as pd
import numpy as np
from indicators import calculate_dema


def calculate_dema_tradingview_style(series: pd.Series, period: int = 200) -> pd.Series:
    """
    TradingView风格的DEMA计算
    使用标准的EMA算法: alpha = 2 / (period + 1)
    """
    alpha = 2.0 / (period + 1)
    
    # 计算第一个EMA
    ema1 = pd.Series(index=series.index, dtype=float)
    ema1.iloc[0] = series.iloc[0]
    
    for i in range(1, len(series)):
        ema1.iloc[i] = alpha * series.iloc[i] + (1 - alpha) * ema1.iloc[i-1]
    
    # 计算第二个EMA
    ema2 = pd.Series(index=series.index, dtype=float)
    ema2.iloc[0] = ema1.iloc[0]
    
    for i in range(1, len(ema1)):
        ema2.iloc[i] = alpha * ema1.iloc[i] + (1 - alpha) * ema2.iloc[i-1]
    
    # DEMA = 2 * EMA1 - EMA2
    dema = 2 * ema1 - ema2
    return dema


def calculate_dema_with_adjust(series: pd.Series, period: int = 200) -> pd.Series:
    """
    使用 adjust=True 的DEMA计算
    """
    ema1 = series.ewm(span=period, adjust=True).mean()
    ema2 = ema1.ewm(span=period, adjust=True).mean()
    dema = 2 * ema1 - ema2
    return dema


def calculate_dema_with_com(series: pd.Series, period: int = 200) -> pd.Series:
    """
    使用 com 参数而不是 span
    com = (span - 1) / 2
    """
    com = (period - 1) / 2
    ema1 = series.ewm(com=com, adjust=False).mean()
    ema2 = ema1.ewm(com=com, adjust=False).mean()
    dema = 2 * ema1 - ema2
    return dema


# 生成测试数据（模拟ETH价格）
np.random.seed(42)
prices = np.array([1900 + np.cumsum(np.random.randn(300) * 5)]).flatten()
prices = np.maximum(prices, 1800)  # 确保价格为正

series = pd.Series(prices)

# 计算不同方式的DEMA
print("=" * 70)
print("DEMA计算方式对比 (最后10个值)")
print("=" * 70)

dema_current = calculate_dema(series, 200)
dema_tv_style = calculate_dema_tradingview_style(series, 200)
dema_adjust_true = calculate_dema_with_adjust(series, 200)
dema_com = calculate_dema_with_com(series, 200)

print(f"\n{'Index':<8} {'Current(adjust=F)':<20} {'TV Style':<20} {'adjust=True':<20} {'COM':<20}")
print("-" * 90)

for i in range(-10, 0):
    idx = len(series) + i
    print(f"{idx:<8} {dema_current.iloc[i]:<20.2f} {dema_tv_style.iloc[i]:<20.2f} {dema_adjust_true.iloc[i]:<20.2f} {dema_com.iloc[i]:<20.2f}")

print("\n" + "=" * 70)
print("差异分析")
print("=" * 70)

# 最后一个值的差异
diff_tv = abs(dema_current.iloc[-1] - dema_tv_style.iloc[-1])
diff_adjust = abs(dema_current.iloc[-1] - dema_adjust_true.iloc[-1])
diff_com = abs(dema_current.iloc[-1] - dema_com.iloc[-1])

print(f"\n最后一条的差异:")
print(f"  Current vs TV-Style: {diff_tv:.2f}")
print(f"  Current vs adjust=True: {diff_adjust:.2f}")
print(f"  Current vs COM: {diff_com:.2f}")

print(f"\n均值差异:")
print(f"  Current vs TV-Style: {(dema_current - dema_tv_style).abs().mean():.2f}")
print(f"  Current vs adjust=True: {(dema_current - dema_adjust_true).abs().mean():.2f}")
print(f"  Current vs COM: {(dema_current - dema_com).abs().mean():.2f}")

# 查看EMA中间值
print("\n" + "=" * 70)
print("EMA中间步骤对比 (最后5个值)")
print("=" * 70)

ema1_current = series.ewm(span=200, adjust=False).mean()
ema2_current = ema1_current.ewm(span=200, adjust=False).mean()

ema1_tv = series.ewm(span=200, adjust=False).mean()  # 先看span是否正确
ema2_tv = ema1_tv.ewm(span=200, adjust=False).mean()

print(f"\n{'Index':<8} {'EMA1-Current':<20} {'EMA1-TV':<20} {'EMA2-Current':<20} {'EMA2-TV':<20}")
print("-" * 90)

for i in range(-5, 0):
    idx = len(series) + i
    print(f"{idx:<8} {ema1_current.iloc[i]:<20.2f} {ema1_tv.iloc[i]:<20.2f} {ema2_current.iloc[i]:<20.2f} {ema2_tv.iloc[i]:<20.2f}")

print("\n" + "=" * 70)
print("关键发现:")
print("=" * 70)
print(f"""
1. 当前实现使用 span={200}, adjust=False
2. 如果与TradingView差异大，可能需要调整：
   - 改用 adjust=True 
   - 改用 com 参数
   - 改用完整的TV风格EMA计算

3. 预期的差异原因：
   - pandas使用不同的初始EMA计算
   - adjust参数影响权重分配
   - span vs com的转换公式
""")
