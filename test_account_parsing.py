#!/usr/bin/env python3
"""
模拟不同的account API返回数据
测试脚本如何处理各种格式
"""

import sys
sys.path.insert(0, '/workspaces/ETH_Perp_Trading_bot')

from gate_client import GateClient

def test_account_parsing():
    """测试account字段提取"""
    
    print("\n" + "="*80)
    print("测试不同account数据格式的处理")
    print("="*80 + "\n")
    
    # 模拟GateClient中的_safe_float方法
    def _safe_float(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0
    
    # 测试场景1: 正常情况
    print("【场景1: 正常的list返回 (包含total字段)】")
    data1 = [
        {
            "currency": "USDT",
            "total": "714.13",
            "available": "476.10",
            "unrealised_pnl": "-0.5"
        }
    ]
    entry = data1[0]
    total = _safe_float(entry.get('total', entry.get('equity', 0)))
    available = _safe_float(entry.get('available', entry.get('free', 0)))
    print(f"  返回: total={total}, available={available}")
    print(f"  脚本会选择: {total if total > 0 else available}\n")
    
    # 测试场景2: 没有total但有equity
    print("【场景2: 返回equity而非total】")
    data2 = [
        {
            "currency": "USDT",
            "equity": "714.13",
            "available": "476.10"
        }
    ]
    entry = data2[0]
    total = _safe_float(entry.get('total', entry.get('equity', 0)))
    available = _safe_float(entry.get('available', entry.get('free', 0)))
    print(f"  返回: total={total}, available={available}")
    print(f"  脚本会选择: {total if total > 0 else available}\n")
    
    # 测试场景3: 字段为0或空
    print("【场景3: 所有字段都是0or空】")
    data3 = [
        {
            "currency": "USDT",
            "total": "0",
            "available": "0"
        }
    ]
    entry = data3[0]
    total = _safe_float(entry.get('total', entry.get('equity', 0)))
    available = _safe_float(entry.get('available', entry.get('free', 0)))
    print(f"  返回: total={total}, available={available}")
    print(f"  脚本会选择: {total if total > 0 else (available if available > 0 else 500)}\n")
    
    # 测试场景4: dict返回
    print("【场景4: dict格式返回】")
    data4 = {
        "currency": "USDT",
        "total": "714.13",
        "available": "476.10",
        "unrealised_pnl": "-0.5"
    }
    total = _safe_float(data4.get('total', data4.get('equity', 0)))
    available = _safe_float(data4.get('available', data4.get('free', 0)))
    print(f"  返回: total={total}, available={available}")
    print(f"  脚本会选择: {total if total > 0 else available}\n")
    
    # 测试场景5: wallet_balance 和 free
    print("【场景5: 使用wallet_balance和free】")
    data5 = {
        "currency": "USDT",
        "wallet_balance": "714.13",
        "free": "476.10"
    }
    total = _safe_float(data5.get('total', data5.get('equity', data5.get('wallet_balance', 0))))
    available = _safe_float(data5.get('available', data5.get('free', 0)))
    print(f"  返回: total={total}, available={available}")  
    print(f"  脚本会选择: {total if total > 0 else available}\n")
    
    print("="*80)
    print("测试结论: 脚本应该能正确提取700+的本金值")
    print("="*80 + "\n")

if __name__ == "__main__":
    test_account_parsing()
