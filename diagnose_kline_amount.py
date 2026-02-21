"""
关键诊断: 确定最优的历史K线数量
"""

import pandas as pd
import sys

sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
from indicators import calculate_dema


def find_optimal_kline_size():
    """
    测试不同K线数量对DEMA的影响
    """
    print("\n" + "=" * 100)
    print("【关键发现】K线数量会极大影响DEMA值！")
    print("=" * 100)
    
    client = GateClient()
    
    sizes = [100, 150, 200, 250, 300, 350, 400, 450, 500]
    results = {}
    
    print(f"\n【DEMA值 vs 历史K线数量】")
    print(f"{'K线数':<8} {'最后K线时间':<25} {'收盘价':<12} {'DEMA':<15} {'与上一个的差异':<18}")
    print("-" * 90)
    
    prev_dema = None
    
    for size in sizes:
        try:
            df = client.get_candlesticks("ETH_USDT", "1h", size)
            dema = calculate_dema(df['close'], 200)
            
            # 获取倒数第二个值（上一根完整K线）
            last_idx = len(df) - 2
            if last_idx >= 0:
                ts = str(df.index[last_idx])
                close = df['close'].iloc[last_idx]
                dema_val = dema.iloc[last_idx]
                
                results[size] = {
                    'time': ts,
                    'close': close,
                    'dema': dema_val
                }
                
                if prev_dema is not None:
                    diff = abs(dema_val - prev_dema)
                    diff_str = f"{diff:.2f}"
                else:
                    diff_str = "-"
                
                print(f"{size:<8} {ts:<25} {close:<12.2f} {dema_val:<15.2f} {diff_str:<18}")
                prev_dema = dema_val
        except Exception as e:
            print(f"{size:<8} 获取失败: {str(e)[:50]}")
    
    print(f"\n【关键数据总结】")
    
    # 找出值变化最大的地方
    dema_values = [v['dema'] for v in results.values()]
    min_dema = min(dema_values)
    max_dema = max(dema_values)
    
    print(f"  最小DEMA: {min_dema:.2f}")
    print(f"  最大DEMA: {max_dema:.2f}")
    print(f"  范围差异: {max_dema - min_dema:.2f}")
    print(f"  百分比: {(max_dema - min_dema) / min_dema * 100:.2f}%")
    
    print(f"\n【比较与TradingView】")
    tv_dema = 1925.64
    print(f"  TradingView DEMA: {tv_dema:.2f}")
    
    for size, data in results.items():
        diff = abs(data['dema'] - tv_dema)
        print(f"  {size}根K线的DEMA: {data['dema']:.2f} (差异: {diff:.2f})")
    
    print(f"\n【结论】")
    print(f"""
DEMA值会随着历史K线数量的增加而变化。
这是完全正常的——更多历史数据 = 更准确的DEMA值。

可能的解决方案：
1. 如果用500根K线还是1933左右，说明需要更多数据
2. 或者TradingView使用了不同的算法/初始化方式
3. 或者TradingView的K线数据本身就不同

建议：检查一下TradingView在该K线上启用了多少个周期的历史数据
""")
    
    return results


def compare_with_alternative_init():
    """
    对比不同初始化方式在大数据量下的效果
    """
    print(f"\n\n" + "=" * 100)
    print("【尝试不同的初始化方式】")
    print("=" * 100)
    
    client = GateClient()
    df = client.get_candlesticks("ETH_USDT", "1h", 500)
    
    # 方式1: 当前实现
    from indicators import calculate_dema
    dema_current = calculate_dema(df['close'], 200)
    
    # 方式2: 更多历史的SMA初始
    ema1_alpha = 2.0 / 201
    ema1 = pd.Series(index=df.index, dtype=float)
    ema1.iloc[0] = df['close'].iloc[0]
    for i in range(1, len(df)):
        ema1.iloc[i] = ema1_alpha * df['close'].iloc[i] + (1 - ema1_alpha) * ema1.iloc[i-1]
    
    ema2 = pd.Series(index=df.index, dtype=float)
    ema2.iloc[0] = ema1.iloc[0]
    for i in range(1, len(df)):
        ema2.iloc[i] = ema1_alpha * ema1.iloc[i] + (1 - ema1_alpha) * ema2.iloc[i-1]
    
    dema_alt = 2 * ema1 - ema2
    
    print(f"\n【最后K线对比】")
    print(f"  当前实现: {dema_current.iloc[-2]:.2f}")
    print(f"  替代方式: {dema_alt.iloc[-2]:.2f}")
    print(f"  TradingView: 1925.64")
    
    print(f"\n差异对比：")
    print(f"  当前 vs TV: {abs(dema_current.iloc[-2] - 1925.64):.2f}")
    print(f"  替代 vs TV: {abs(dema_alt.iloc[-2] - 1925.64):.2f}")


if __name__ == '__main__':
    import pandas as pd
    
    results = find_optimal_kline_size()
    compare_with_alternative_init()
