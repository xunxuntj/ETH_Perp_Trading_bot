#!/usr/bin/env python3
"""
打印完整的Gate.io账户信息
看看API返回了什么字段
"""

import sys
import json
sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
from config import GATE_API_KEY, GATE_API_SECRET

def print_account_info():
    """打印账户完整信息"""
    print("\n" + "="*80)
    print("Gate.io 账户信息完整打印")
    print("="*80 + "\n")
    
    try:
        # 创建debug模式的client，输出详细信息
        client = GateClient(GATE_API_KEY, GATE_API_SECRET, debug=True)
        
        print("【调用 client.get_account()】\n")
        account = client.get_account()
        
        print("\n【处理后返回的account字典】")
        print(json.dumps(account, indent=2, ensure_ascii=False))
        
        print("\n【各字段值】")
        print(f"  total: {account.get('total')} (类型: {type(account.get('total'))})")
        print(f"  available: {account.get('available')} (类型: {type(account.get('available'))})")
        print(f"  unrealised_pnl: {account.get('unrealised_pnl')} (类型: {type(account.get('unrealised_pnl'))})")
        
        print("\n【应该显示的本金】")
        print(f"  脚本会使用: {account.get('total', account.get('available', 500))}")
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print_account_info()
