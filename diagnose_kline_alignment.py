"""
诊断K线时间戳和数据对齐问题
"""

import pandas as pd
import sys
from datetime import datetime, timezone

sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
from indicators import calculate_dema


def diagnose_kline_alignment(contract="ETH_USDT"):
    """
    诊断K线数据的时间对齐问题
    """
    print("\n" + "=" * 100)
    print("K线数据时间戳对齐诊断")
    print("=" * 100)
    
    client = GateClient()
    
    # 获取1H和30m数据
    df_1h = client.get_candlesticks(contract, "1h", 50)
    df_30m = client.get_candlesticks(contract, "30m", 100)
    
    print(f"\n【1H K线信息】")
    print(f"  总数: {len(df_1h)}")
    print(f"  列名: {list(df_1h.columns)}")
    print(f"  索引类型: {type(df_1h.index)}")
    
    print(f"\n【最后10根1H K线】")
    print(f"{'Idx':<5} {'时间':<25} {'开':<10} {'高':<10} {'低':<10} {'收':<10} {'量':<15}")
    print("-" * 100)
    
    for i in range(-10, 0):
        idx = len(df_1h) + i
        row = df_1h.iloc[i]
        
        # 尝试解析时间戳
        if hasattr(df_1h.index, 'to_pydatetime'):
            ts = df_1h.index[idx].to_pydatetime()
        else:
            ts = datetime.fromtimestamp(df_1h.index[idx], tz=timezone.utc) if isinstance(df_1h.index[idx], (int, float)) else df_1h.index[idx]
        
        print(f"{idx:<5} {str(ts):<25} {row['open']:<10.2f} {row['high']:<10.2f} {row['low']:<10.2f} {row['close']:<10.2f} {row.get('volume', 0):<15.2f}")
    
    print(f"\n【30m K线信息】")
    print(f"  总数: {len(df_30m)}")
    
    print(f"\n【最后20根30m K线】")
    print(f"{'Idx':<5} {'时间':<25} {'收':<10}")
    print("-" * 60)
    
    for i in range(-20, 0):
        idx = len(df_30m) + i
        row = df_30m.iloc[i]
        
        # 尝试解析时间戳
        if hasattr(df_30m.index, 'to_pydatetime'):
            ts = df_30m.index[idx].to_pydatetime()
        else:
            ts = datetime.fromtimestamp(df_30m.index[idx], tz=timezone.utc) if isinstance(df_30m.index[idx], (int, float)) else df_30m.index[idx]
        
        print(f"{idx:<5} {str(ts):<25} {row['close']:<10.2f}")
    
    # 检查是否存在 'time' 列
    print(f"\n【检查dataframe的完整信息】")
    print(f"\n1H数据的head:")
    print(df_1h.head(2))
    
    print(f"\n1H数据的tail:")
    print(df_1h.tail(2))
    
    # 计算DEMA并检查值
    print(f"\n【DEMA计算检查】")
    dema_1h = calculate_dema(df_1h['close'], 200)
    
    print(f"\n最后5根1H K线的DEMA值:")
    for i in range(-5, 0):
        idx = len(df_1h) + i
        print(f"  iloc[{i}] (idx={idx}): close={df_1h['close'].iloc[i]:.2f}, dema={dema_1h.iloc[i]:.2f}")
    
    print(f"\n用于交易的值 (iloc[-2]):")
    print(f"  Close: {df_1h['close'].iloc[-2]:.2f}")
    print(f"  DEMA:  {dema_1h.iloc[-2]:.2f}")
    
    # 数据质量检查
    print(f"\n【数据质量检查】")
    print(f"1H close 是否有NaN: {df_1h['close'].isna().any()}")
    print(f"1H close 值域: {df_1h['close'].min():.2f} - {df_1h['close'].max():.2f}")
    print(f"1H close 平均值: {df_1h['close'].mean():.2f}")
    print(f"DEMA 是否有NaN: {dema_1h.isna().any()}")
    print(f"DEMA 有效值数: {dema_1h.notna().sum()}")
    
    return df_1h, dema_1h


if __name__ == '__main__':
    print("\n开始K线对齐诊断...")
    
    try:
        df_1h, dema_1h = diagnose_kline_alignment()
        print("\n✓ 诊断完成")
    except Exception as e:
        print(f"\n✗ 诊断失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
