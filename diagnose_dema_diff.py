"""
诊断DEMA差异 - 对比TradingView PineScript和pandas实现
"""

import pandas as pd
import numpy as np
import sys
import os

# 添加项目路径
sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from indicators import calculate_dema
from gate_client import GateClient
from config import DEMA_PERIOD


def calculate_dema_pinescript_style(df: pd.DataFrame, period: int = 200):
    """
    严格按照TradingView PineScript的方式计算DEMA
    
    ta.ema() 使用的标准EMA公式:
    alpha = 2 / (period + 1)
    EMA_t = alpha * price_t + (1 - alpha) * EMA_{t-1}
    """
    close = df['close'].values
    n = len(close)
    
    # 计算第一个EMA
    alpha = 2.0 / (period + 1)
    ema1 = np.zeros(n)
    ema1[0] = close[0]
    
    for i in range(1, n):
        ema1[i] = alpha * close[i] + (1 - alpha) * ema1[i - 1]
    
    # 计算第二个EMA
    ema2 = np.zeros(n)
    ema2[0] = ema1[0]
    
    for i in range(1, n):
        ema2[i] = alpha * ema1[i] + (1 - alpha) * ema2[i - 1]
    
    # DEMA = 2 * ema1 - ema2
    dema = 2 * ema1 - ema2
    
    return pd.DataFrame({
        'ema1': ema1,
        'ema2': ema2,
        'dema': dema,
        'close': close
    }, index=df.index)


def compare_dema_implementations(df_1h):
    """
    对比两种DEMA实现方式
    """
    print("\n" + "=" * 90)
    print("DEMA 计算对比")
    print("=" * 90)
    
    # 方式1: 当前实现 (pandas ewm adjust=False)
    dema_current = calculate_dema(df_1h['close'], DEMA_PERIOD)
    
    # 方式2: PineScript风格 (标准EMA递推)
    dema_pinescript_df = calculate_dema_pinescript_style(df_1h, DEMA_PERIOD)
    dema_pinescript = dema_pinescript_df['dema']
    
    # 方式3: pandas ewm adjust=True
    ema1_adjust_true = df_1h['close'].ewm(span=DEMA_PERIOD, adjust=True).mean()
    ema2_adjust_true = ema1_adjust_true.ewm(span=DEMA_PERIOD, adjust=True).mean()
    dema_adjust_true = 2 * ema1_adjust_true - ema2_adjust_true
    
    print(f"\n【K线数据统计】")
    print(f"  总K线数: {len(df_1h)}")
    print(f"  收盘价范围: {df_1h['close'].min():.2f} - {df_1h['close'].max():.2f}")
    print(f"  最后一根K线收盘: {df_1h['close'].iloc[-1]:.2f}")
    
    print(f"\n【最后10根K线的DEMA对比】")
    print(f"{'Index':<6} {'Close':<10} {'Current':<15} {'PineScript':<15} {'Adjust=T':<15} {'差异1':<10} {'差异2':<10}")
    print("-" * 90)
    
    for i in range(-10, 0):
        idx = len(df_1h) + i
        c = dema_current.iloc[i]
        p = dema_pinescript.iloc[i]
        a = dema_adjust_true.iloc[i]
        close = df_1h['close'].iloc[i]
        
        diff1 = abs(c - p)
        diff2 = abs(c - a)
        
        print(f"{idx:<6} {close:<10.2f} {c:<15.2f} {p:<15.2f} {a:<15.2f} {diff1:<10.2f} {diff2:<10.2f}")
    
    print("\n【最后一根K线 (上一根完整K线 = iloc[-2]) 详细对比】")
    last_idx = -2
    c_val = dema_current.iloc[last_idx]
    p_val = dema_pinescript.iloc[last_idx]
    a_val = dema_adjust_true.iloc[last_idx]
    
    print(f"  当前实现 (adjust=False):  {c_val:.2f}")
    print(f"  PineScript风格 (标准EMA): {p_val:.2f}")
    print(f"  Adjust=True方式:          {a_val:.2f}")
    print(f"\n  差异 (Current vs PineScript): {abs(c_val - p_val):.2f} ({abs(c_val - p_val)/p_val*100:.2f}%)")
    print(f"  差异 (Current vs Adjust=T):  {abs(c_val - a_val):.2f} ({abs(c_val - a_val)/a_val*100:.2f}%)")
    
    # EMA中间步骤对比
    print(f"\n【EMA中间步骤对比 (最后5根K线)】")
    print(f"{'Idx':<6} {'Close':<10} {'EMA1-Current':<15} {'EMA1-PineScript':<18} {'EMA2-Current':<15} {'EMA2-PineScript':<18}")
    print("-" * 90)
    
    ema1_current = df_1h['close'].ewm(span=DEMA_PERIOD, adjust=False).mean()
    ema2_current = ema1_current.ewm(span=DEMA_PERIOD, adjust=False).mean()
    
    for i in range(-5, 0):
        idx = len(df_1h) + i
        close = df_1h['close'].iloc[i]
        e1c = ema1_current.iloc[i]
        e1p = dema_pinescript_df['ema1'].iloc[i]
        e2c = ema2_current.iloc[i]
        e2p = dema_pinescript_df['ema2'].iloc[i]
        
        print(f"{idx:<6} {close:<10.2f} {e1c:<15.2f} {e1p:<18.2f} {e2c:<15.2f} {e2p:<18.2f}")
    
    # 统计分析
    diff_all = (dema_current - dema_pinescript).abs()
    print(f"\n【全局差异统计】")
    print(f"  Mean diff (Current vs PineScript): {diff_all.mean():.4f}")
    print(f"  Max diff:                         {diff_all.max():.4f}")
    print(f"  Min diff:                         {diff_all.min():.4f}")
    print(f"  Std diff:                         {diff_all.std():.4f}")
    
    return {
        'current': dema_current,
        'pinescript': dema_pinescript,
        'adjust_true': dema_adjust_true,
        'ema1_current': ema1_current,
        'ema2_current': ema2_current,
        'ema1_pinescript': dema_pinescript_df['ema1'],
        'ema2_pinescript': dema_pinescript_df['ema2'],
    }


if __name__ == '__main__':
    print("\n" + "=" * 90)
    print("开始诊断DEMA计算差异")
    print("=" * 90)
    
    # 初始化客户端
    try:
        client = GateClient()
        print("\n✓ Gate.io API 连接成功")
    except Exception as e:
        print(f"\n✗ Gate.io API 连接失败: {e}")
        sys.exit(1)
    
    # 获取1H K线数据
    try:
        df_1h = client.get_candlesticks("ETH_USDT", "1h", 300)
        print(f"✓ 获取1H K线数据成功，共 {len(df_1h)} 根K线")
    except Exception as e:
        print(f"✗ 获取K线数据失败: {e}")
        sys.exit(1)
    
    # 对比DEMA实现
    results = compare_dema_implementations(df_1h)
    
    print("\n" + "=" * 90)
    print("诊断完成")
    print("=" * 90)
    print("""
【建议】
1. 如果 "Current vs PineScript" 差异较大 (>1%)，应该改用 PineScript 风格的EMA计算
2. 如果两者都与TradingView差异大，可能是：
   - K线数据不同步（检查时间戳对齐）
   - 计算周期不对齐（使用 iloc[-2] 确保完整K线）
   - 数据源不同（确认使用同一交易所同一合约）

【总结】
如果发现差异，建议：
- 替换 calculate_dema() 函数为 calculate_dema_pinescript_style() 的方式
- 确保K线时间对齐（使用 iloc[-2] 表示上一根完整K线）
""")
