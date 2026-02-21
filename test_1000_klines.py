"""
测试1000根K线的DEMA计算精度
"""

import sys
sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
from indicators import calculate_dema


def test_1000_klines():
    """
    测试1000根K线的DEMA值
    """
    print("\n" + "=" * 100)
    print("1000根K线 DEMA精度测试")
    print("=" * 100)
    
    client = GateClient()
    
    # 获取1000根K线
    print(f"\n正在获取1000根K线数据...")
    df_1h = client.get_candlesticks("ETH_USDT", "1h", 1000)
    
    print(f"\n【数据信息】")
    print(f"  获取K线数: {len(df_1h)}")
    print(f"  时间范围: {df_1h.index[0]} 到 {df_1h.index[-1]}")
    print(f"  时间跨度: {(df_1h.index[-1] - df_1h.index[0]).days} 天")
    print(f"  收盘价范围: {df_1h['close'].min():.2f} - {df_1h['close'].max():.2f}")
    
    # 计算DEMA
    print(f"\n计算DEMA (周期=200)...")
    dema_1h = calculate_dema(df_1h['close'], 200)
    
    # 获取最后K线的DEMA
    last_complete_idx = -2  # 上一根完整K线
    
    print(f"\n【结果对比】")
    print(f"  K线时间 (iloc[-2]): {df_1h.index[last_complete_idx]}")
    print(f"  收盘价: {df_1h['close'].iloc[last_complete_idx]:.2f}")
    print(f"  EMA1: {df_1h['close'].ewm(span=200, adjust=False).mean().iloc[last_complete_idx]:.2f}")
    ema1 = df_1h['close'].ewm(span=200, adjust=False).mean()
    ema2 = ema1.ewm(span=200, adjust=False).mean()
    print(f"  EMA2: {ema2.iloc[last_complete_idx]:.2f}")
    print(f"  DEMA: {dema_1h.iloc[last_complete_idx]:.2f}")
    
    local_dema = dema_1h.iloc[last_complete_idx]
    tv_dema = 1925.64
    
    print(f"\n【与TradingView对比】")
    print(f"  本地 DEMA:    {local_dema:.2f}")
    print(f"  TradingView:  {tv_dema:.2f}")
    print(f"  差异:         {abs(local_dema - tv_dema):.2f}")
    print(f"  差异百分比:   {abs(local_dema - tv_dema) / tv_dema * 100:.2f}%")
    
    # 显示最近20根的DEMA值
    print(f"\n【最后20根K线的DEMA值】")
    print(f"{'索引':<6} {'时间':<20} {'收盘':<12} {'DEMA':<12}")
    print("-" * 60)
    
    for i in range(-20, 0):
        idx = len(df_1h) + i
        ts = str(df_1h.index[i])[:16]
        close = df_1h['close'].iloc[i]
        dema_val = dema_1h.iloc[i]
        print(f"{idx:<6} {ts:<20} {close:<12.2f} {dema_val:<12.2f}")
    
    # 分析长期趋势
    print(f"\n【长期DEMA趋势】")
    print(f"  DEMA第一个值: {dema_1h.iloc[0]:.2f}")
    print(f"  DEMA中间值: {dema_1h.iloc[len(dema_1h)//2]:.2f}")
    print(f"  DEMA最后值: {dema_1h.iloc[-1]:.2f}")
    print(f"  变化范围: {abs(dema_1h.iloc[-1] - dema_1h.iloc[0]):.2f}")
    
    return {
        'dema': local_dema,
        'diff': abs(local_dema - tv_dema),
        'percent': abs(local_dema - tv_dema) / tv_dema * 100,
        'tv': tv_dema
    }


def compare_all_sizes():
    """
    完整对比所有数据量
    """
    print(f"\n\n" + "=" * 100)
    print("完整数据量对比")
    print("=" * 100)
    
    client = GateClient()
    sizes = [300, 500, 750, 1000]
    
    print(f"\n【同一K线在不同数据量下的DEMA值对比】")
    print(f"{'数据量':<8} {'DEMA值':<12} {'vs TV':<12} {'差异%':<10} {'改进':<10}")
    print("-" * 60)
    
    prev_diff = None
    results = {}
    
    for size in sizes:
        try:
            df = client.get_candlesticks("ETH_USDT", "1h", size)
            dema = calculate_dema(df['close'], 200)
            dema_val = dema.iloc[-2]
            
            tv_dema = 1925.64
            diff = abs(dema_val - tv_dema)
            percent = diff / tv_dema * 100
            
            results[size] = dema_val
            
            if prev_diff is not None:
                improve = prev_diff - diff
                improve_str = f"{improve:+.2f}"
            else:
                improve_str = "-"
            
            print(f"{size:<8} {dema_val:<12.2f} {diff:<12.2f} {percent:<10.2f}% {improve_str:<10}")
            prev_diff = diff
            
        except Exception as e:
            print(f"{size:<8} 错误: {str(e)[:40]}")
    
    print(f"\n【最佳选择】")
    best_size = min(results.items(), key=lambda x: abs(x[1] - 1925.64))
    print(f"  最接近TradingView的配置: {best_size[0]}根K线")
    print(f"  DEMA值: {best_size[1]:.2f}")
    print(f"  差异: {abs(best_size[1] - 1925.64):.2f}")


if __name__ == '__main__':
    result = test_1000_klines()
    compare_all_sizes()
    
    print(f"\n\n【建议】")
    if result['diff'] < 5:
        print(f"✅ 1000根K线的精度非常好（差异{result['diff']:.2f}，< 5）")
        print(f"   建议改用1000根K线")
    elif result['diff'] < 10:
        print(f"✅ 1000根K线的精度不错（差异{result['diff']:.2f}，< 10）")
        print(f"   建议改用1000根K线")
    else:
        print(f"⚠️  1000根K线差异{result['diff']:.2f}，可能需要进一步优化")
