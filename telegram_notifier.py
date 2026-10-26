"""
Telegram 通知模块
"""

import os
import requests
from typing import Optional


class TelegramNotifier:
    """Telegram 通知器"""
    
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        raw_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN', '')
        raw_chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID', '')
        self.bot_token = str(raw_token).strip().strip('"').strip("'") if raw_token else ""
        self.chat_id = str(raw_chat_id).strip().strip('"').strip("'") if raw_chat_id else ""
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        
    def send(self, message: str, parse_mode: Optional[str] = "HTML") -> bool:
        """
        发送消息到 Telegram
        
        Args:
            message: 消息内容
            parse_mode: 解析模式 (HTML 或 Markdown)
            
        Returns:
            是否发送成功
        """
        if not self.bot_token or not self.chat_id:
            print("⚠️ Telegram 未配置 (缺少 BOT_TOKEN 或 CHAT_ID)")
            return False
        
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_web_page_preview": True
        }

        # Only include parse_mode when explicitly provided and not None
        if parse_mode:
            payload["parse_mode"] = parse_mode
        
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return True
            else:
                print(f"⚠️ Telegram 发送失败: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            print(f"⚠️ Telegram 发送异常: {e}")
            return False
    
    def send_signal(self, signal_message: str) -> bool:
        """
        发送交易信号
        将信号格式转换为 Telegram 友好格式
        """
        # 转义 HTML 特殊字符（如果需要）
        # 目前信号已经是纯文本，直接发送（不指定 parse_mode）
        return self.send(signal_message, parse_mode=None)

    def send_document(self, file_path: str, caption: Optional[str] = None, parse_mode: Optional[str] = "HTML") -> bool:
        """
        发送文档/文件到 Telegram
        """
        if not self.bot_token or not self.chat_id:
            print("⚠️ Telegram 未配置 (缺少 BOT_TOKEN 或 CHAT_ID)")
            return False
        
        url = f"{self.base_url}/sendDocument"
        try:
            with open(file_path, 'rb') as f:
                files = {'document': f}
                payload = {'chat_id': self.chat_id}
                if caption:
                    payload['caption'] = caption
                if parse_mode:
                    payload['parse_mode'] = parse_mode
                resp = requests.post(url, data=payload, files=files, timeout=20)
                if resp.status_code == 200:
                    return True
                else:
                    print(f"⚠️ Telegram 发送文档失败: {resp.status_code} - {resp.text}")
                    if "chat not found" in resp.text:
                        masked = self.chat_id[:4] + "***" if len(self.chat_id) > 4 else self.chat_id
                        print(f"ℹ️ [排查建议] 当前发送目标 chat_id 为: '{masked}' (长度: {len(self.chat_id)})")
                        print("   1. 若为个人会话：请确认已在 Telegram 找到该 Bot 并点击过 /start 激活；")
                        print("   2. 若为群组/频道：请确认 Bot 已被加入群组且为管理员；若为 Supergroup/Channel，chat_id 必须以 -100 开头；")
                        print("   3. 请核对 GitHub Secrets 中的 TELEGRAM_CHAT_ID 是否正确。")
                    elif "bot was kicked" in resp.text:
                        print("ℹ️ [排查建议] Bot 已被移出群组/频道，请重新将 Bot 添加进群组并设为管理员。")
                    return False
        except Exception as e:
            print(f"⚠️ Telegram 发送文档异常: {e}")
            return False


def send_telegram_message(message: str) -> bool:
    """
    便捷函数：发送 Telegram 消息
    使用环境变量中的配置
    """
    notifier = TelegramNotifier()
    return notifier.send_signal(message)


def send_telegram_document(file_path: str, caption: Optional[str] = None, parse_mode: Optional[str] = "HTML") -> bool:
    """
    便捷函数：发送 Telegram 文档
    使用环境变量中的配置
    """
    notifier = TelegramNotifier()
    return notifier.send_document(file_path, caption, parse_mode)


# 测试
if __name__ == "__main__":
    # 测试发送
    test_message = """🔴 开空信号！

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 开空 18张 @ 2703.89
📌 设止损 @ 2758.09
━━━━━━━━━━━━━━━━━━━━━━━━━

【过滤条件检查】
• 1H ST: 🔴红 ✅
• 1H收盘 2698.77 < DEMA 2800.55 ✅
• 30m ST: 🔴红 ✅

【仓位计算】
• 止损距离: 54.20点
• 保证金: 48.67U (10x)
• 风险: 固定 10.00U
• 锁利阈值: 2698.33"""
    
    if send_telegram_message(test_message):
        print("✅ 测试消息发送成功")
    else:
        print("❌ 测试消息发送失败")
