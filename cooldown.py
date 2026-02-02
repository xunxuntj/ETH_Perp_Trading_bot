"""
冷静期检查模块
通过 Gate.io API 获取交易历史，判断是否触发冷静期
"""

from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

from gate_client import GateClient
from config import MAX_CONSECUTIVE_LOSSES, CIRCUIT_BREAKER_EQUITY


@dataclass
class CooldownStatus:
    """冷静期状态"""
    triggered: bool = False
    reason: str = ""
    cooldown_hours: int = 0
    consecutive_losses: int = 0
    last_loss_time: Optional[datetime] = None
    details: str = ""


def check_cooldown(client: GateClient, contract: str = "ETH_USDT") -> CooldownStatus:
    """
    检查是否处于冷静期
    
    规则:
    1. 连续 3 笔止损亏损离场 → 强制休息 48 小时
    2. 本金 ≤ 350U → 停手 1 周
    
    返回: CooldownStatus
    """
    
    # 1. 检查本金
    try:
        account = client.get_account()
        # 熔断检查用 total: 包含已占用保证金 + 未实现盈亏
        # 这样可以捕获本金因浮损而严重缩水的情况
        equity = account['total']
        
        if equity <= CIRCUIT_BREAKER_EQUITY:
            return CooldownStatus(
                triggered=True,
                reason="capital_circuit_breaker",
                cooldown_hours=168,  # 1 周
                details=f"本金 {equity:.2f}U ≤ {CIRCUIT_BREAKER_EQUITY}U，停手 1 周"
            )
    except Exception as e:
        # API 调用失败，继续检查其他条件
        equity = None
    
    # 2. 检查连续亏损
    try:
        closes = client.get_position_closes(contract, limit=10)
        
        if not closes:
            return CooldownStatus(
                triggered=False,
                details="无平仓记录"
            )
        
        # 统计连续亏损次数（从最近开始往前数）
        consecutive_losses = 0
        last_loss_time = None
        
        for close in closes:
            pnl = close['pnl']
            
            if pnl < 0:  # 亏损
                consecutive_losses += 1
                if last_loss_time is None:
                    last_loss_time = datetime.fromtimestamp(close['time'], tz=timezone.utc)
            else:
                # 遇到盈利，停止计数
                break
        
        if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            # 检查是否已过 48 小时
            if last_loss_time:
                now = datetime.now(timezone.utc)
                hours_since = (now - last_loss_time).total_seconds() / 3600
                
                if hours_since < 48:
                    return CooldownStatus(
                        triggered=True,
                        reason="consecutive_loss",
                        cooldown_hours=48,
                        consecutive_losses=consecutive_losses,
                        last_loss_time=last_loss_time,
                        details=f"连续 {consecutive_losses} 笔亏损，需休息 48 小时\n"
                                f"最后亏损: {last_loss_time.strftime('%Y-%m-%d %H:%M UTC')}\n"
                                f"已过: {hours_since:.1f} 小时\n"
                                f"剩余: {48 - hours_since:.1f} 小时"
                    )
                else:
                    # 已过 48 小时，冷静期结束
                    return CooldownStatus(
                        triggered=False,
                        consecutive_losses=consecutive_losses,
                        details=f"连续 {consecutive_losses} 笔亏损，但已过 48 小时冷静期"
                    )
        
        # 未触发冷静期
        return CooldownStatus(
            triggered=False,
            consecutive_losses=consecutive_losses,
            details=f"最近连续亏损: {consecutive_losses} 笔 (阈值: {MAX_CONSECUTIVE_LOSSES})"
        )
        
    except Exception as e:
        return CooldownStatus(
            triggered=False,
            details=f"获取交易历史失败: {str(e)}"
        )


def format_recent_trades(client: GateClient, contract: str = "ETH_USDT", limit: int = 5) -> str:
    """
    格式化最近的平仓记录
    """
    try:
        closes = client.get_position_closes(contract, limit=limit)
        
        if not closes:
            return "无平仓记录"
        
        lines = ["最近平仓记录:"]
        for i, close in enumerate(closes, 1):
            time_str = datetime.fromtimestamp(close['time'], tz=timezone.utc).strftime('%m-%d %H:%M')
            pnl = close['pnl']
            emoji = "🟢" if pnl >= 0 else "🔴"
            side = "多" if close['side'] == 'long' else "空"
            lines.append(f"  {i}. {time_str} {side} {emoji} {pnl:+.2f}U")
        
        return "\n".join(lines)
        
    except Exception as e:
        return f"获取记录失败: {str(e)}"
