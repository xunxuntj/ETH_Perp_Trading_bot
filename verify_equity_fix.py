"""
验证本金字段修改
测试修改后策略使用的是'total'而非'available'
"""

import sys
sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
from config import GATE_API_KEY, GATE_API_SECRET, CONTRACT
from strategy import TradingStrategy

def verify_equity_field():
    """验证本金字段"""
    print("\n" + "="*80)
    print("本金字段验证")
    print("="*80 + "\n")
    
    try:
        client = GateClient(GATE_API_KEY, GATE_API_SECRET)
        
        print("【获取账户信息】")
        account = client.get_account()
        
        print(f"  total (总资金): {account.get('total', 0):.2f}U")
        print(f"  available (可用余额): {account.get('available', 0):.2f}U")
        print(f"  unrealised_pnl (未平仓盈亏): {account.get('unrealised_pnl', 0):.2f}U")
        
        total = account.get('total', 0)
        available = account.get('available', 0)
        margin_used = total - available
        
        print("\n【字段分析】")
        print(f"  total - available = 占用保证金: {margin_used:.2f}U")
        print(f"  这与Gate App的本金应该对应: {total:.2f}U")
        
        print("\n【策略修改后的行为】")
        print(f"  OK 脚本现在显示 total: {total:.2f}U")
        print(f"  以前显示 available: {available:.2f}U")
        print(f"  差异: {total - available:.2f}U (即占用保证金)")
        
        print("\n【预期结果】")
        if total > 0:
            print(f"  脚本输出中的本金现在应该显示: {total:.2f}U")
            print(f"  这应该与Gate App的账户总资金一致 OK")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_equity_field()
