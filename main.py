#!/usr/bin/env python3
"""
Post-ETF V1 Classic Multi-Asset Quantitative Trading Script.
Executes signal analysis, risk management, and order execution across:
  - BTC_USDT (35% weight)
  - ETH_USDT (30% weight)
  - SOL_USDT (25% weight)
  - DOGE_USDT (10% weight)

Usage:
  python main.py

Environment Variables:
  GATE_API_KEY        - Gate.io API Key
  GATE_API_SECRET     - Gate.io API Secret
  TELEGRAM_BOT_TOKEN  - Telegram Bot Token
  TELEGRAM_CHAT_ID    - Telegram Chat ID
  ENABLE_AUTO_TRADING - Enable Live Trading (true/false, default: false)
"""

import os
import sys
import json
from datetime import datetime, timezone

from config import GATE_API_KEY, GATE_API_SECRET, PORTFOLIO_BASKET, PORTFOLIO_WEIGHTS, ENABLE_AUTO_TRADING, SIGNAL_NOTIFY_MODE
from gate_client import GateClient
from execution_flow import ExecutionFlow
from telegram_notifier import send_telegram_message


def main():
    # 检查 API 配置
    if not GATE_API_KEY or not GATE_API_SECRET:
        print("❌ 请设置 GATE_API_KEY 和 GATE_API_SECRET 环境变量")
        sys.exit(1)
    
    now = datetime.now(timezone.utc)
    print(f"🕐 {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)
    print(f"🚀 V1 POST-ETF MULTI-ASSET PORTFOLIO EXECUTOR")
    print(f"📦 Active Basket: {', '.join(PORTFOLIO_BASKET)}")
    print("=" * 65)
    
    # 显示模式
    mode = "✅ 自动交易模式 (Live Trading)" if ENABLE_AUTO_TRADING else "⚠️ 模拟/信号模式 (Signal Only)"
    print(f"🔧 {mode}\n")
    
    try:
        # 初始化 Gate.io 客户端
        client = GateClient(GATE_API_KEY, GATE_API_SECRET)
        
        # 遍历组合中的四大合约进行独立策略计算与交易执行
        for contract in PORTFOLIO_BASKET:
            print(f"\n" + "-" * 50)
            print(f"🔍 [CONTRACT: {contract}] (Weight: {PORTFOLIO_WEIGHTS.get(contract, 0.25)*100:.0f}%)")
            print("-" * 50)

            flow = ExecutionFlow(client, contract)
            result = flow.execute_strategy_and_trade()
            
            strategy_action = result.get("strategy_action")
            trade_executed = result.get("trade_executed")
            message = result.get("message", "")
            
            print(f"📋 策略动作: {strategy_action}")
            if trade_executed:
                print(f"✅ 交易已在 Gate.io 执行")
            else:
                print(f"⚠️ 未产生新交易操作")
            
            print(f"\n{message}")
            
            trade_details = result.get("trade_details", {})
            if trade_details:
                print(f"\n📊 详情: {json.dumps(trade_details, indent=2, ensure_ascii=False)}")
            
            notify_actions = [
                "open_long", "open_short", "close", "close_and_reverse_long",
                "close_and_reverse_short", "reverse_to_long", "reverse_to_short",
                "stop_updated", "enter_locked", "switch_1h", "circuit_breaker", "cooldown"
            ]
            
            should_notify = (SIGNAL_NOTIFY_MODE == "all") or (SIGNAL_NOTIFY_MODE == "operation" and strategy_action in notify_actions)
            
            if should_notify:
                formatted_message = f"[{contract}] {message}"
                send_telegram_message(formatted_message)
        
        print("\n" + "=" * 65)
        print("✅ 全多资产组合周期巡检完成！")
        print("=" * 65)
        
    except Exception as e:
        error_msg = f"❌ V1 组合执行脚本异常: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        send_telegram_message(f"⚠️ 组合交易脚本错误\n\n{error_msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
