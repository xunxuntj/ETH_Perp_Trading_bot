"""
测试2000根K线的DEMA精度
Gate.io API K线获取上限是2000，测试能否进一步提升精度
"""

import sys
sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
from indicators import calculate_dema
import os

# API配置
CONTRACT = "ETH_USDT"
DEMA_PERIOD = 200
TV_DEMA = 1925.64  # TradingView参考值

def test_2000_klines():
    """测试2000根K线的DEMA精度"""
    print("\n" + "="*80)
    print("="*80)
    print("2000根K线 DEMA精度测试 (Gate.io API最大限制)")
    print("="*80)
    print("="*80 + "\n")
    
    client = GateClient()
    
    print("正在获取2000根K线数据...")
    df_1h = client.get_candlesticks(CONTRACT, "1h", 2000)
    
    print(f"\n【数据信息】")
    print(f"  获取K线数: {len(df_1h)}")
    print(f"  时间范围: {df_1h.index[0]} 到 {df_1h.index[-1]}")
    
    # 计算时间跨度
    time_diff = df_1h.index[-1] - df_1h.index[0]
    days = time_diff.days
    print(f"  时间跨度: {days} 天")
    print(f"  收盘价范围: {df_1h['close'].min():.2f} - {df_1h['close'].max():.2f}")
    
    print(f"\n计算DEMA (周期={DEMA_PERIOD})...")
    dema_1h = calculate_dema(df_1h['close'], DEMA_PERIOD)
    
    # 获取上一根完整K线的DEMA
    local_dema = dema_1h.iloc[-2]
    kline_time = df_1h.index[-2]
    close_price = df_1h['close'].iloc[-2]
    
    diff = abs(local_dema - TV_DEMA)
    diff_percent = (diff / TV_DEMA) * 100
    
    print(f"\n【结果对比】")
    print(f"  K线时间 (iloc[-2]): {kline_time}")
    print(f"  收盘价: {close_price:.2f}")
    print(f"  DEMA: {local_dema:.2f}")
    
    print(f"\n【与TradingView对比】")
    print(f"  本地 DEMA:    {local_dema:.2f}")
    print(f"  TradingView:  {TV_DEMA:.2f}")
    print(f"  差异:         {diff:.2f}")
    print(f"  差异百分比:   {diff_percent:.4f}%")
    
    # 显示最后20根K线
    print(f"\n【最后20根K线的DEMA值】")
    print(f"{'索引':<6} {'时间':<20} {'收盘':<12} {'DEMA':<12}")
    print("-" * 65)
    
    start_idx = max(0, len(df_1h) - 20)
    for i in range(start_idx, len(df_1h)):
        time_str = str(df_1h.index[i])
        close = df_1h['close'].iloc[i]
        dema = dema_1h.iloc[i]
        print(f"{i:<6} {time_str:<20} {close:<12.2f} {dema:<12.2f}")
    
    print(f"\n【长期DEMA趋势】")
    print(f"  DEMA第一个值: {dema_1h.iloc[0]:.2f}")
    print(f"  DEMA中间值: {dema_1h.iloc[len(dema_1h)//2]:.2f}")
    print(f"  DEMA最后值: {dema_1h.iloc[-1]:.2f}")
    print(f"  变化范围: {dema_1h.max() - dema_1h.min():.2f}")
    
    return local_dema, diff


def compare_all_sizes():
    """对比不同K线数量(300/500/750/1000/1500/2000)的精度"""
    print("\n" + "="*80)
    print("="*80)
    print("完整数据量对比 (包括2000根)")
    print("="*80)
    print("="*80 + "\n")
    
    client = GateClient()
    results = []
    
    sizes = [300, 500, 750, 1000, 1500, 2000]
    
    for size in sizes:
        print(f"正在获取 {size} 根K线...")
        df = client.get_candlesticks(CONTRACT, "1h", size)
        dema = calculate_dema(df['close'], DEMA_PERIOD)
        local_dema = dema.iloc[-2]
        diff = abs(local_dema - TV_DEMA)
        diff_percent = (diff / TV_DEMA) * 100
        results.append({
            'size': size,
            'dema': local_dema,
            'diff': diff,
            'diff_percent': diff_percent
        })
    
    print(f"\n【同一K线在不同数据量下的DEMA值对比】")
    print(f"{'数据量':<10} {'DEMA值':<12} {'vs TV':<12} {'差异%':<12} {'改进':<15}")
    print("-" * 60)
    
    prev_diff = None
    for r in results:
        diff_text = f"±{r['diff']:.2f}"
        
        if prev_diff is None:
            improvement = "-"
        else:
            improvement_val = prev_diff - r['diff']
            improvement = f"↓{improvement_val:.2f}" if improvement_val > 0 else f"↑{abs(improvement_val):.2f}"
        
        print(f"{r['size']:<10} {r['dema']:<12.2f} {diff_text:<12} {r['diff_percent']:<12.4f}% {improvement:<15}")
        prev_diff = r['diff']
    
    # 找出最优配置
    best = min(results, key=lambda x: x['diff'])
    print(f"\n【最佳选择】")
    print(f"  最接近TradingView的配置: {best['size']}根K线")
    print(f"  DEMA值: {best['dema']:.2f}")
    print(f"  差异: {best['diff']:.2f}")
    
    # 分析建议
    print(f"\n【建议】")
    
    # 精度判定
    if best['size'] == 2000:
        if best['diff'] < 0.07:
            print(f"✅ 2000根K线的精度更优（差异{best['diff']:.2f} < 0.07）")
            print(f"   但性能成本增加: API响应时间可能增加20-30%")
            print(f"   实际差异降低: {((0.07 - best['diff']) / 0.07 * 100):.1f}%")
            print(f"   建议: 如对精度有极端要求，可升级到2000根（通常1000根足够）")
        else:
            print(f"✅ 1000根K线已经足够最优")
            print(f"   2000根没有明显改进，不建议升级")
    else:
        print(f"✅ {best['size']}根K线是最优配置")
        print(f"   当前已采用1000根，性能和精度平衡最佳")


if __name__ == "__main__":
    try:
        # 运行2000根K线测试
        dema_2000, diff_2000 = test_2000_klines()
        
        # 运行完整对比
        compare_all_sizes()
        
        print("\n" + "="*80)
        print("测试完成！")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
