#!/usr/bin/env python3
"""
Gate.io API 测试脚本
用法: python3 test_gate_api.py <API_KEY> <API_SECRET> [CONTRACT]
例如: python3 test_gate_api.py your_api_key your_api_secret ETH_USDT
"""

import sys
import json
import os
import pytest
from gate_client import GateClient

# Skip these live API tests when API keys are not provided in the environment
pytestmark = pytest.mark.skipif(
    not os.environ.get('GATE_API_KEY') or not os.environ.get('GATE_API_SECRET'),
    reason='Gate API keys not provided, skipping live API tests'
)


def print_header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def test_get_account(client):
    """测试获取账户信息"""
    print_header("1. 获取账户信息 (get_account)")
    try:
        account = client.get_account()
        print(json.dumps(account, indent=2, ensure_ascii=False))
        print(f"\n✅ 成功!")
        print(f"  可用余额: {account['available']:.2f} USDT")
        print(f"  总余额: {account['total']:.2f} USDT")
        print(f"  未实现盈亏: {account['unrealised_pnl']:+.2f} USDT")
        return account
    except Exception as e:
        print(f"❌ 失败: {e}")
        return None


def test_get_ticker(client, contract):
    """测试获取最新价格"""
    print_header(f"2. 获取最新价格 (get_ticker {contract})")
    try:
        ticker = client.get_ticker(contract)
        print(json.dumps(ticker, indent=2, ensure_ascii=False))
        print(f"\n✅ 成功!")
        print(f"  最新价: {ticker['last']:.2f}")
        print(f"  标记价: {ticker['mark_price']:.2f}")
        return ticker
    except Exception as e:
        print(f"❌ 失败: {e}")
        return None


def test_get_positions(client, contract):
    """测试获取持仓"""
    print_header(f"3. 获取持仓 (get_positions {contract})")
    try:
        position = client.get_positions(contract)
        if position is None:
            print("✅ 无持仓 (这是正常的)")
            return None
        print(json.dumps(position, indent=2, ensure_ascii=False))
        print(f"\n✅ 有持仓!")
        print(f"  方向: {'多' if position['size'] > 0 else '空'}")
        print(f"  张数: {abs(position['size'])}")
        print(f"  入场价: {position['entry_price']:.2f}")
        print(f"  当前标记价: {position['mark_price']:.2f}")
        print(f"  未实现盈亏: {position['unrealised_pnl']:+.2f}")
        return position
    except Exception as e:
        print(f"❌ 失败: {e}")
        return None


def test_get_candlesticks(client, contract):
    """测试获取K线数据"""
    print_header(f"4. 获取K线数据 (get_candlesticks {contract})")
    try:
        df = client.get_candlesticks(contract, interval="30m", limit=5)
        print("✅ 成功! 最近 5 根 30m K线:")
        print(df.tail())
        print(f"\n  共获取 {len(df)} 根 K线")
        return df
    except Exception as e:
        print(f"❌ 失败: {e}")
        return None


def test_get_position_closes(client, contract):
    """测试获取平仓记录"""
    print_header(f"5. 获取平仓记录 (get_position_closes {contract})")
    try:
        closes = client.get_position_closes(contract, limit=5)
        if not closes:
            print("✅ 无平仓记录")
            return []
        
        print(f"✅ 成功! 最近 {len(closes)} 条平仓记录:")
        for i, close in enumerate(closes, 1):
            from datetime import datetime, timezone
            time_str = datetime.fromtimestamp(close['time'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            side = "多" if close['side'] == 'long' else "空"
            print(f"  {i}. {time_str} {side} PnL: {close['pnl']:+.2f}U")
        
        return closes
    except Exception as e:
        print(f"❌ 失败: {e}")
        return []


def test_get_my_trades(client, contract):
    """测试获取成交记录"""
    print_header(f"6. 获取成交记录 (get_my_trades {contract})")
    try:
        trades = client.get_my_trades(contract, limit=5)
        if not trades:
            print("✅ 无成交记录")
            return []
        
        print(f"✅ 成功! 最近 {len(trades)} 条成交记录:")
        for i, trade in enumerate(trades, 1):
            from datetime import datetime, timezone
            time_str = datetime.fromtimestamp(trade['time'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            side = "买" if trade['size'] > 0 else "卖"
            print(f"  {i}. {time_str} {side} {abs(trade['size'])} @ {trade['price']:.2f}")
        
        return trades
    except Exception as e:
        print(f"❌ 失败: {e}")
        return []


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("\n示例:")
        print("  python3 test_gate_api.py your_api_key your_api_secret")
        print("  python3 test_gate_api.py your_api_key your_api_secret BTC_USDT")
        sys.exit(1)
    
    api_key = sys.argv[1]
    api_secret = sys.argv[2]
    contract = sys.argv[3] if len(sys.argv) > 3 else "ETH_USDT"
    
    print(f"🔑 API Key: {api_key[:10]}...")
    print(f"🔐 Contract: {contract}")
    
    client = GateClient(api_key=api_key, api_secret=api_secret)
    
    # 运行测试
    account = test_get_account(client)
    ticker = test_get_ticker(client, contract)
    position = test_get_positions(client, contract)
    candlesticks = test_get_candlesticks(client, contract)
    closes = test_get_position_closes(client, contract)
    trades = test_get_my_trades(client, contract)
    
    # 总结
    print_header("📋 测试总结")
    print("\n✅ 所有测试完成!")
    print("\n关键信息:")
    if account:
        print(f"  • 账户可用: {account['available']:.2f} USDT")
        print(f"  • 账户总计: {account['total']:.2f} USDT")
    if ticker:
        print(f"  • {contract} 当前价: {ticker['last']:.2f}")
    if position is None:
        print(f"  • {contract} 无持仓")
    else:
        print(f"  • {contract} 持仓: {'多' if position['size'] > 0 else '空'} {abs(position['size'])} 张")
    
    print("\n💡 如果有任何 ❌ 错误，请检查:")
    print("  1. API Key 和 Secret 是否正确")
    print("  2. API 密钥是否已启用相应权限 (USDT 永续合约)")
    print("  3. 网络连接是否正常")


if __name__ == '__main__':
    main()
