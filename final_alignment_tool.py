"""
最终DEMA对齐工具 - 找出确切的差异根源
"""

import pandas as pd
import sys

sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
from indicators import calculate_dema


def create_alignment_table():
    """
    创建可与TradingView对比的完整表格
    """
    print("\n" + "=" * 120)
    print("DEMA对齐工具 - 与TradingView逐K线对比")
    print("=" * 120)
    
    client = GateClient()
    
    # 获取足够数据
    df_1h = client.get_candlesticks("ETH_USDT", "1h", 500)
    dema_1h = calculate_dema(df_1h['close'], 200)
    
    print(f"\n【使用本脚本的方法】")
    print(f"""
步骤1: 在TradingView上找一根K线，记下：
       - K线时间（如: 2026-02-21 04:00:00）
       - 该K线的收盘价（如: 1961.50）
       - 该K线的DEMA值（如: ?）

步骤2: 在下面的表格中找到时间相同的K线

步骤3: 对比两个系统的DEMA值

步骤4: 如果有差异，告诉我时间、收盘价、和两个DEMA值
""")
    
    print(f"\n【本地计算的所有K线 - 可用于与TradingView逐个对比】")
    print(f"格式: 时间 | 收盘价 | DEMA值\n")
    
    # 生成所有K线的对比表
    print(f"{'时间':<25} | {'收盘价':<10} | {'DEMA':<12} | {'Close-DEMA':<12}")
    print("-" * 75)
    
    # 显示最近50根
    for i in range(-50, 0):
        idx = len(df_1h) + i
        ts = str(df_1h.index[i])
        close = df_1h['close'].iloc[i]
        dema_val = dema_1h.iloc[i]
        diff = close - dema_val
        
        # 用符号标记最后一根完整K线
        marker = " ← 上一根完整K线" if i == -2 else ""
        print(f"{ts:<25} | {close:<10.2f} | {dema_val:<12.2f} | {diff:<12.2f}{marker}")
    
    print(f"\n【关键K线】")
    print(f"  iloc[-2] (上一根完整): {df_1h.index[-2]} close={df_1h['close'].iloc[-2]:.2f} DEMA={dema_1h.iloc[-2]:.2f}")
    print(f"  iloc[-1] (当前形成中): {df_1h.index[-1]} close={df_1h['close'].iloc[-1]:.2f} DEMA={dema_1h.iloc[-1]:.2f}")
    
    return df_1h, dema_1h


def analyze_specific_kline(tv_time, tv_close, tv_dema):
    """
    分析用户给出的特定K线
    """
    print(f"\n\n" + "=" * 100)
    print("特定K线分析")
    print("=" * 100)
    
    client = GateClient()
    df_1h = client.get_candlesticks("ETH_USDT", "1h", 500)
    dema_1h = calculate_dema(df_1h['close'], 200)
    
    print(f"\n【TradingView的K线】")
    print(f"  时间: {tv_time}")
    print(f"  收盘价: {tv_close}")
    print(f"  DEMA: {tv_dema}")
    
    # 在本地找相同时间的K线
    try:
        # 尝试匹配时间
        matching_rows = df_1h[df_1h.index.strftime('%Y-%m-%d %H:%M:%S') == tv_time]
        
        if len(matching_rows) > 0:
            idx = matching_rows.index[0]
            local_idx_in_df = df_1h.index.get_loc(idx)
            close = df_1h['close'].iloc[local_idx_in_df]
            dema_val = dema_1h.iloc[local_idx_in_df]
            
            print(f"\n【本地的相同时间K线】")
            print(f"  时间: {idx}")
            print(f"  收盘价: {close:.2f}")
            print(f"  DEMA: {dema_val:.2f}")
            
            print(f"\n【对比分析】")
            close_diff = abs(close - tv_close)
            dema_diff = abs(dema_val - tv_dema)
            
            print(f"  收盘价差异: {close_diff:.2f} ({close_diff/tv_close*100:.2f}%)")
            print(f"  DEMA差异: {dema_diff:.2f} ({dema_diff/tv_dema*100:.2f}%)")
            
            if close_diff > 0.01:
                print(f"\n  ⚠️  K线基础数据就不同！")
                print(f"     原因: 可能使用不同的数据源（交易所、合约）")
                print(f"     建议: 确认TradingView使用的是Gate.io ETH_USDT的数据")
            elif dema_diff > 1:
                print(f"\n  ⚠️  K线数据相同，但DEMA不同！")
                print(f"     可能原因：")
                print(f"     1. 初始化方式不同（SMA vs 直接使用第一值）")
                print(f"     2. 历史K线不完全相同")
                print(f"     3. 使用了不同的周期")
            else:
                print(f"\n  ✅ 完全匹配！没有问题")
        else:
            print(f"\n  ❌ 找不到该时间的K线")
            print(f"     时间范围: {df_1h.index[0]} 到 {df_1h.index[-1]}")
            
    except Exception as e:
        print(f"  分析失败: {e}")


if __name__ == '__main__':
    # 生成完整表格
    df_1h, dema_1h = create_alignment_table()
    
    print(f"\n\n" + "=" * 100)
    print("【使用说明】")
    print("=" * 100)
    print("""
1. 把上面的表保存下来
2. 在TradingView上找一根K线（比如用收盘价搜索）
3. 记下那根线的：
   - 确切时间戳（UTC）
   - 收盘价
   - 该K线的DEMA值
4. 对比本表中的相同时间/收盘价的K线

如果有不匹配的地方，回复我以下信息：
   TradingView: 时间=?, 收盘=?, DEMA=?
   本地: 时间=?, 收盘=?, DEMA=?
   差异: ?

这样我能精准定位问题所在。
""")
