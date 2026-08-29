"""
残留遗留挂单清理工具 (Orphan Order Sweeper)
扫描 PORTFOLIO_BASKET 中所有无持仓但存在残留限价单/触发单的合约，并强制取消清理。
"""

import sys
import os
import json
from config import GATE_API_KEY, GATE_API_SECRET, PORTFOLIO_BASKET
from gate_client import GateClient

def sweep_orphan_orders():
    print("============================================================")
    print("🧹 交易所残留孤立挂单/触发单全面扫描与清理")
    print("============================================================")
    
    if not GATE_API_KEY or not GATE_API_SECRET:
        print("⚠️ 警告：未配置 GATE_API_KEY 或 GATE_API_SECRET，无法连接 Gate.io 实盘 API。")
        return

    client = GateClient(GATE_API_KEY, GATE_API_SECRET)
    
    for symbol in PORTFOLIO_BASKET:
        print(f"\n🔍 检查 [{symbol}] 持仓与挂单状态...")
        try:
            position = client.get_positions(symbol)
            pos_size = position.get('size', 0) if position else 0
            
            orders = client.get_orders(symbol, status="open")
            price_orders = client.get_price_orders(symbol, status="open")
            
            print(f"  ├─ 当前持仓: {pos_size} 张")
            print(f"  ├─ 限价挂单: {len(orders)} 笔")
            print(f"  └─ 触发条件单: {len(price_orders)} 笔")
            
            if pos_size == 0 and (len(orders) > 0 or len(price_orders) > 0):
                print(f"  🚨 检测到 [{symbol}] 无持仓但存在 {len(orders)} 笔限价单 & {len(price_orders)} 笔触发单，发起强制清理...")
                try:
                    res1 = client.cancel_orders(contract=symbol)
                    print(f"     ✅ 成功取消限价挂单: {json.dumps(res1)}")
                except Exception as ex1:
                    print(f"     ⚠️ 取消限价挂单提示: {ex1}")
                    
                try:
                    res2 = client.cancel_price_orders(contract=symbol)
                    print(f"     ✅ 成功取消触发条件单: {len(res2)} 笔")
                except Exception as ex2:
                    print(f"     ⚠️ 取消触发条件单提示: {ex2}")
            elif pos_size == 0 and len(orders) == 0 and len(price_orders) == 0:
                print(f"  ✅ [{symbol}] 盘面干净，无残留挂单。")
            else:
                print(f"  ℹ️ [{symbol}] 处于正常持仓中，保留相关挂单与止损触发单。")
                
        except Exception as e:
            print(f"  ❌ [{symbol}] 检查与清理异常: {e}")

if __name__ == "__main__":
    sweep_orphan_orders()
