"""
组合全币种杠杆一键同步工具 (Force Sync Portfolio Leverage)
将 PORTFOLIO_BASKET 中的所有合约杠杆强制修正为 10x
"""

import sys
import os
import json
from config import GATE_API_KEY, GATE_API_SECRET, PORTFOLIO_BASKET, LEVERAGE
from gate_client import GateClient

def sync_all_leverage():
    print(f"============================================================")
    print(f"🛡️ 组合杠杆安全配置检修与强制同步 (目标杠杆: {LEVERAGE}x)")
    print(f"============================================================")
    
    if not GATE_API_KEY or not GATE_API_SECRET:
        print("⚠️ 警告：未配置 GATE_API_KEY 或 GATE_API_SECRET，无法连接 Gate.io 实盘 API。")
        return
        
    client = GateClient(GATE_API_KEY, GATE_API_SECRET)
    
    for symbol in PORTFOLIO_BASKET:
        print(f"\n🔍 检查 [{symbol}] 当前杠杆配置...")
        try:
            pos_detail = client.get_position_detail(symbol)
        except Exception as e:
            print(f"⚠️ [{symbol}] 获取持仓详情异常: {e}")
            pos_detail = None
            
        pos_margin_mode = pos_detail.get("pos_margin_mode", "cross") if pos_detail else "cross"
        curr_lev = int(pos_detail.get("leverage", 0)) if pos_detail else 0
        curr_cross_limit = int(pos_detail.get("cross_leverage_limit", 0)) if pos_detail else 0
        
        print(f"  └─ 当前模式: {pos_margin_mode}, 逐仓杠杆: {curr_lev}x, 全仓上限: {curr_cross_limit}x")
        
        # 统一尝试强制修正为 10x
        success = False
        # 1. 尝试按当前模式设置
        if pos_margin_mode == "cross":
            try:
                res = client.update_position_leverage(symbol, leverage="0", cross_leverage_limit=str(LEVERAGE))
                print(f"  ✅ [{symbol}] 已成功将全仓杠杆限制修正为 {LEVERAGE}x: {json.dumps(res)}")
                success = True
            except Exception as ex1:
                print(f"  ⚠️ [{symbol}] 全仓模式修正失败: {ex1}，尝试逐仓模式修正...")
                try:
                    res = client.update_position_leverage(symbol, leverage=str(LEVERAGE), cross_leverage_limit="")
                    print(f"  ✅ [{symbol}] 已成功将逐仓杠杆修正为 {LEVERAGE}x: {json.dumps(res)}")
                    success = True
                except Exception as ex2:
                    print(f"  ❌ [{symbol}] 逐仓模式修正亦失败: {ex2}")
        else: # isolated
            try:
                res = client.update_position_leverage(symbol, leverage=str(LEVERAGE), cross_leverage_limit="")
                print(f"  ✅ [{symbol}] 已成功将逐仓杠杆修正为 {LEVERAGE}x: {json.dumps(res)}")
                success = True
            except Exception as ex1:
                print(f"  ⚠️ [{symbol}] 逐仓模式修正失败: {ex1}，尝试全仓模式修正...")
                try:
                    res = client.update_position_leverage(symbol, leverage="0", cross_leverage_limit=str(LEVERAGE))
                    print(f"  ✅ [{symbol}] 已成功将全仓杠杆限制修正为 {LEVERAGE}x: {json.dumps(res)}")
                    success = True
                except Exception as ex2:
                    print(f"  ❌ [{symbol}] 全仓模式修正亦失败: {ex2}")
                    
        if not success:
            print(f"🚨 警告: [{symbol}] 杠杆未能成功修正为 10x，请核实交易所是否有未平仓挂单阻碍修改。")

if __name__ == "__main__":
    sync_all_leverage()
