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

from config import GATE_API_KEY, GATE_API_SECRET, CONTRACT, ENABLE_AUTO_TRADING, SIGNAL_NOTIFY_MODE
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
        
        # 兜底：止损相关异常强制推送，避免遗漏关键风控信息
        debug_enabled = bool(os.getenv("DEBUG") or os.getenv("GATE_DEBUG"))
        message_lower = message.lower()
        stop_loss_fallback = (
            ("stop_loss" in message_lower or "止损" in message_lower)
            and any(keyword in message_lower for keyword in ["失败", "异常", "未执行", "error", "failed"])
        )

        notify_message = message
        if stop_loss_fallback and debug_enabled:
            strategy_details = trade_details.get("strategy_details", {}) if isinstance(trade_details, dict) else {}
            executor_result = trade_details.get("executor_result", {}) if isinstance(trade_details, dict) else {}

            old_stop = strategy_details.get("old_stop")
            new_stop = strategy_details.get("stop_loss")
            exec_success = executor_result.get("success")
            exec_msg = executor_result.get("message")

            debug_lines = [
                "",
                "[DEBUG:FALLBACK_NOTIFY]",
                f"strategy_action={strategy_action}",
                f"trade_executed={trade_executed}",
            ]
            if old_stop is not None:
                debug_lines.append(f"old_stop={old_stop}")
            if new_stop is not None:
                debug_lines.append(f"new_stop={new_stop}")
            if exec_success is not None:
                debug_lines.append(f"executor_success={exec_success}")
            if exec_msg:
                debug_lines.append(f"executor_message={exec_msg}")

            notify_message = message + "\n" + "\n".join(debug_lines)

        # 发送 Telegram 通知
        should_notify = False
        if SIGNAL_NOTIFY_MODE == "all":
            should_notify = True
        elif SIGNAL_NOTIFY_MODE == "operation":
            should_notify = (strategy_action in notify_actions or stop_loss_fallback)
        elif SIGNAL_NOTIFY_MODE == "report":
            should_notify = False
        else:
            should_notify = (strategy_action in notify_actions or stop_loss_fallback)

        if should_notify:
            # 在消息最开头加上交易对标识，方便明确是 ETH 还是 BTC
            formatted_message = f"[{CONTRACT}] {notify_message}"
            success = send_telegram_message(formatted_message)
            if success:
                print("\n📱 Telegram 通知已发送")
            else:
                print("\n⚠️ Telegram 通知发送失败")
        else:
            print(f"\n📴 动作 '{strategy_action}' (模式: {SIGNAL_NOTIFY_MODE}) 不需要通知")
        
        # GitHub Actions summary
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
                f.write(f"## {CONTRACT} Trading Signal\n\n")
                f.write(f"**Time:** {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n")
                f.write(f"**Mode:** {'🤖 Auto Trading' if ENABLE_AUTO_TRADING else '🔔 Signal Only'}\n\n")
                f.write(f"**Action:** `{strategy_action}`\n\n")
                f.write(f"**Execute:** {'✅ Yes' if trade_executed else '❌ No'}\n\n")
                f.write(f"```\n{message}\n```\n")
        
        # 保存执行日志（生产环境）
        if ENABLE_AUTO_TRADING and trade_executed:
            try:
                log_file = "execution_log.json" if CONTRACT == "ETH_USDT" else f"execution_log_{CONTRACT.lower()}.json"
                flow.save_execution_log(log_file)
            except Exception as e:
                print(f"⚠️ 保存执行日志失败: {str(e)}")
        
        print("\n✅ 完成")
        
    except Exception as e:
        error_msg = f"❌ 脚本错误: {str(e)}"
        print(error_msg)
        
        import traceback
        traceback.print_exc()
        
        # 错误也发送通知
        send_telegram_message(f"⚠️ {CONTRACT}交易脚本错误\n\n{error_msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
