#!/usr/bin/env python3
"""
ETH 趋势交易监控脚本
V9.6-Exec SOP

用法:
  python main.py

环境变量:
  GATE_API_KEY       - Gate.io API Key
  GATE_API_SECRET    - Gate.io API Secret
  TELEGRAM_BOT_TOKEN - Telegram Bot Token
  TELEGRAM_CHAT_ID   - Telegram Chat ID
  ENABLE_AUTO_TRADING- 启用自动交易 (true/false, 默认false)

GitHub Actions 调度: 每30分钟运行一次
"""

import os
import sys
import json
from datetime import datetime, timezone

from config import GATE_API_KEY, GATE_API_SECRET, CONTRACT, ENABLE_AUTO_TRADING
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
    print("=" * 55)
    
    # 显示模式
    mode = "✅ 自动交易模式" if ENABLE_AUTO_TRADING else "⚠️ 模拟（信号）模式"
    print(f"🔧 {mode}\n")
    
    try:
        # 初始化
        client = GateClient(GATE_API_KEY, GATE_API_SECRET)
        flow = ExecutionFlow(client, CONTRACT)
        
        # 执行完整流程：策略分析 + 交易执行
        result = flow.execute_strategy_and_trade()
        
        # 输出结果
        strategy_action = result.get("strategy_action")
        trade_executed = result.get("trade_executed")
        message = result.get("message", "")
        
        print(f"\n📋 策略: {strategy_action}")
        if trade_executed:
            print(f"✅ 交易已执行")
        else:
            print(f"⚠️ 未执行交易")
        
        print(f"\n{message}")
        
        # 输出详情
        trade_details = result.get("trade_details", {})
        if trade_details:
            print(f"\n📊 详情: {json.dumps(trade_details, indent=2, ensure_ascii=False)}")
        
        # 需要通知的动作类型
        notify_actions = [
            # 开仓信号
            "open_long", 
            "open_short",
            # 平仓信号
            "close",
            "close_and_reverse_long",
            "close_and_reverse_short",
            # 反手建议
            "reverse_to_long",
            "reverse_to_short",
            # 持仓更新 (止损移动/阶段切换)
            "stop_updated",
            "enter_locked",
            "switch_1h",
            # 风控信号
            "circuit_breaker",
            "cooldown",
        ]
        
        # 发送 Telegram 通知
        if strategy_action in notify_actions:
            success = send_telegram_message(message)
            if success:
                print("\n📱 Telegram 通知已发送")
            else:
                print("\n⚠️ Telegram 通知发送失败")
        else:
            print(f"\n📴 动作 '{strategy_action}' 不需要通知")
        
        # GitHub Actions summary
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
                f.write(f"## ETH Trading Signal\n\n")
                f.write(f"**Time:** {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n")
                f.write(f"**Mode:** {'🤖 Auto Trading' if ENABLE_AUTO_TRADING else '🔔 Signal Only'}\n\n")
                f.write(f"**Action:** `{strategy_action}`\n\n")
                f.write(f"**Execute:** {'✅ Yes' if trade_executed else '❌ No'}\n\n")
                f.write(f"```\n{message}\n```\n")
        
        # 保存执行日志（生产环境）
        if ENABLE_AUTO_TRADING and trade_executed:
            try:
                flow.save_execution_log("execution_log.json")
            except Exception as e:
                print(f"⚠️ 保存执行日志失败: {str(e)}")
        
        print("\n✅ 完成")
        
    except Exception as e:
        error_msg = f"❌ 脚本错误: {str(e)}"
        print(error_msg)
        
        import traceback
        traceback.print_exc()
        
        # 错误也发送通知
        send_telegram_message(f"⚠️ ETH交易脚本错误\n\n{error_msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
        
        if result.details:
            print(f"\n📊 详情: {json.dumps(result.details, indent=2, ensure_ascii=False)}")
        
        # 需要通知的动作类型
        notify_actions = [
            # 开仓信号
            "open_long", 
            "open_short",
            # 平仓信号
            "close",
            "close_and_reverse_long",
            "close_and_reverse_short",
            # 持仓更新 (止损移动/阶段切换)
            "stop_updated",
            "enter_locked",
            "switch_1h",
            # 风控信号
            "circuit_breaker",
            "cooldown",
        ]
        
        # 发送 Telegram 通知
        if result.action in notify_actions:
            success = send_telegram_message(result.message)
            if success:
                print("\n📱 Telegram 通知已发送")
            else:
                print("\n⚠️ Telegram 通知发送失败")
        else:
            print(f"\n📴 动作 '{result.action}' 不需要通知")
        
        # GitHub Actions summary
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
                f.write(f"## ETH Trading Signal\n\n")
                f.write(f"**Time:** {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n")
                f.write(f"**Action:** `{result.action}`\n\n")
                f.write(f"```\n{result.message}\n```\n")
        
        print("\n✅ 完成")
        
    except Exception as e:
        error_msg = f"❌ 脚本错误: {str(e)}"
        print(error_msg)
        
        import traceback
        traceback.print_exc()
        
        # 错误也发送通知
        send_telegram_message(f"⚠️ ETH交易脚本错误\n\n{error_msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
