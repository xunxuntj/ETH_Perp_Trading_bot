"""
诊断Gate.io账户信息API返回字段
检查本金("available"vs其他字段)与Gate App显示值的差异
"""

import sys
sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient
import json

def diagnose_account():
    """诊断账户信息"""
    print("\n" + "="*80)
    print("="*80)
    print("Gate.io账户信息诊断")
    print("="*80)
    print("="*80 + "\n")
    
    client = GateClient()
    
    # 获取原始API响应
    print("正在获取账户信息...")
    
    try:
        # 使用GateClient的session和签名方法
        url_path = "/api/v4/futures/usdt/accounts"
        full_url = f"https://api.gateio.ws/api/v4/futures/usdt/accounts"
        
        headers = client._sign("GET", url_path, "", "")
        resp = client.session.get(full_url, headers=headers)
        resp.raise_for_status()
        
        raw_data = resp.json()
        
        print("【原始API响应】")
        print(json.dumps(raw_data, indent=2, ensure_ascii=False))
        
        # 调用get_account方法查看处理后的数据
        account = client.get_account()
        
        print("\n【处理后的account字段】")
        for key, value in account.items():
            print(f"  {key}: {value}")
        
        if isinstance(raw_data, list):
            print(f"\n【USDT账户明细】(list中的第一个USDT条目)")
            usdt_entry = None
            for item in raw_data:
                if str(item.get('currency', '')).upper() == 'USDT':
                    usdt_entry = item
                    break
            if usdt_entry is None and len(raw_data) > 0:
                usdt_entry = raw_data[0]
            
            if usdt_entry:
                print("完整字段:")
                for key, value in usdt_entry.items():
                    print(f"  {key}: {value}")
        
        elif isinstance(raw_data, dict):
            print(f"\n【字典型账户数据】")
            for key, value in raw_data.items():
                print(f"  {key}: {value}")
        
        # 关键字段对比
        print("\n【关键字段对比】")
        if isinstance(raw_data, list):
            for item in raw_data:
                if str(item.get('currency', '')).upper() == 'USDT':
                    print(f"  total (总资金): {item.get('total', 'N/A')}")
                    print(f"  available (可用): {item.get('available', 'N/A')}")
                    print(f"  unrealised_pnl (未平仓盈亏): {item.get('unrealised_pnl', 'N/A')}")
                    print(f"  equity (账户权益): {item.get('equity', 'N/A')}")
                    print(f"  margin (已占用保证金): {item.get('margin', 'N/A')}")
                    break
        elif isinstance(raw_data, dict):
            print(f"  total: {raw_data.get('total', 'N/A')}")
            print(f"  available: {raw_data.get('available', 'N/A')}")
            print(f"  unrealised_pnl: {raw_data.get('unrealised_pnl', 'N/A')}")
            print(f"  equity: {raw_data.get('equity', 'N/A')}")
            print(f"  margin: {raw_data.get('margin', 'N/A')}")
        
        print("\n【用脚本计算出的equity】")
        print(f"  current equity in strategy: {account.get('available', 0.0)}")
        print(f"  vs Gate App应该显示的值: 714.13（需要验证用的是哪个字段）")
        
        # 建议
        print("\n【建议】")
        print("如果脚本显示474.10而Gate App显示714.13:")
        print("  差异: 714.13 - 476.10 = 238.03")
        print("  可能的原因:")
        print("  1. available是已扣除保证金的可用金额")
        print("  2. equity或total才是实际账户总资金")
        print("  3. 需要改用equity字段而非available")
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    diagnose_account()
