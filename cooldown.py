"""
冷静期检查模块
通过 Gate.io API 获取交易历史，判断是否触发冷静期

【冷静期规则】(参见 README.md):
• 连续 3 笔止损 → 强制休息 48 小时
• 本金 ≤ 350U → 熔断停手 1 周

【工作原理】:
1. 获取最近 100 笔交易历史
2. 计算连续止损笔数
3. 根据条件判断是否触发冷静期
4. 保存状态以避免重复通知

【通知管理】:
• 首次触发冷静期：发送 Telegram 通知
• 后续 30 分钟检查：不重复通知
• 冷静期结束：恢复交易
"""

import os
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass

from gate_client import GateClient
from config import MAX_CONSECUTIVE_LOSSES, CIRCUIT_BREAKER_EQUITY, ENABLE_AUTO_TRADING


@dataclass
class CooldownStatus:
    """
    冷静期状态
    
    触发条件：
    • triggered=True: 冷静期已触发
    • reason: 触发原因（连续亏损/熔断等）
    • cooldown_hours: 冷静期时长（小时）
    """
    triggered: bool = False
    reason: str = ""
    cooldown_hours: int = 0
    consecutive_losses: int = 0
    last_loss_time: Optional[datetime] = None
    details: str = ""
    can_trade_time: Optional[datetime] = None  # 何时可以开单
    should_notify: bool = False  # 是否应该推送通知


# 冷静期通知状态文件
COOLDOWN_NOTIFY_STATE_FILE = "cooldown_notify_state.json"
COOLDOWN_STATE_FILE = "cooldown_state.json"


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def load_cooldown_state() -> dict:
    """加载冷静期状态。"""
    default_state = {
        "consecutive_losses": 0,
        "cooldown_until": None,
        "last_loss_time": None,
        "reset_anchor_time": None
    }

    if os.path.exists(COOLDOWN_STATE_FILE):
        try:
            with open(COOLDOWN_STATE_FILE, 'r') as f:
                data = json.load(f)
                default_state.update({
                    "consecutive_losses": int(data.get("consecutive_losses", 0) or 0),
                    "cooldown_until": data.get("cooldown_until"),
                    "last_loss_time": data.get("last_loss_time"),
                    "reset_anchor_time": data.get("reset_anchor_time")
                })
        except Exception:
            pass

    return default_state


def save_cooldown_state(state: dict):
    """保存冷静期状态。"""
    with open(COOLDOWN_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def reset_cooldown_state(reset_anchor_time: Optional[datetime] = None):
    """重置冷静期状态，冷静期结束后从头开始统计。"""
    save_cooldown_state({
        "consecutive_losses": 0,
        "cooldown_until": None,
        "last_loss_time": None,
        "reset_anchor_time": _serialize_datetime(reset_anchor_time)
    })


def record_trade_result(pnl: float, close_time: Optional[datetime] = None):
    """记录一笔已平仓交易结果，用于自动交易模式下的连续亏损统计。

    冷静期内发生的平仓（例如旧仓被止损）不会影响计数或重置计时。
    48 小时自然结束后，计数由 check_cooldown 清零。
    """
    state = load_cooldown_state()
    close_time = close_time or datetime.now(timezone.utc)

    cooldown_until = _parse_datetime(state.get("cooldown_until"))

    # 冷静期仍在进行中 → 本笔交易结果不计入，等待自然结束
    if cooldown_until and close_time < cooldown_until:
        return

    # 冷静期已结束，先清零再统计新结果
    if cooldown_until and close_time >= cooldown_until:
        reset_cooldown_state(reset_anchor_time=cooldown_until)
        state = load_cooldown_state()

    if pnl < 0:
        state["consecutive_losses"] = int(state.get("consecutive_losses", 0)) + 1
        state["last_loss_time"] = _serialize_datetime(close_time)
    else:
        state["consecutive_losses"] = 0
        state["last_loss_time"] = None

    if state["consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES:
        cooldown_until = close_time + timedelta(hours=48)
        state["consecutive_losses"] = MAX_CONSECUTIVE_LOSSES
        state["cooldown_until"] = _serialize_datetime(cooldown_until)
        state["last_loss_time"] = _serialize_datetime(close_time)
    else:
        state["cooldown_until"] = None

    save_cooldown_state(state)


def _build_consecutive_loss_status(consecutive_losses: int) -> CooldownStatus:
    return CooldownStatus(
        triggered=False,
        consecutive_losses=consecutive_losses,
        details=f"最近连续亏损: {consecutive_losses} 笔 (阈值: {MAX_CONSECUTIVE_LOSSES})"
    )


def _check_cooldown_from_state(now: datetime, notify_state: dict) -> CooldownStatus:
    state = load_cooldown_state()
    cooldown_until = _parse_datetime(state.get("cooldown_until"))
    consecutive_losses = int(state.get("consecutive_losses", 0) or 0)
    last_loss_time = _parse_datetime(state.get("last_loss_time"))

    if cooldown_until and now < cooldown_until:
        remaining_hours = (cooldown_until - now).total_seconds() / 3600
        should_notify = not notify_state["notified"]
        if should_notify:
            notify_state["notified"] = True
            notify_state["triggered_at"] = now.isoformat()
            notify_state["notify_count"] = 1
            save_cooldown_notify_state(notify_state)

        last_loss_str = last_loss_time.strftime('%Y-%m-%d %H:%M UTC') if last_loss_time else '未知'
        return CooldownStatus(
            triggered=True,
            reason="consecutive_loss",
            cooldown_hours=48,
            consecutive_losses=consecutive_losses,
            last_loss_time=last_loss_time,
            can_trade_time=cooldown_until,
            should_notify=should_notify,
            details=f"连续 {consecutive_losses} 笔亏损，需休息 48 小时\n"
                    f"最后亏损: {last_loss_str}\n"
                    f"剩余: {remaining_hours:.1f} 小时\n"
                    f"✅ 可开单时间: {cooldown_until.strftime('%Y-%m-%d %H:%M UTC')}"
        )

    if cooldown_until and now >= cooldown_until:
        reset_cooldown_state(reset_anchor_time=cooldown_until)
        reset_cooldown_notify_state()
        return CooldownStatus(
            triggered=False,
            details="48 小时冷静期已结束，连续亏损计数已清零 ✅ 可以开单"
        )

    if notify_state["notified"]:
        reset_cooldown_notify_state()

    return _build_consecutive_loss_status(consecutive_losses)


def _check_cooldown_from_history(client: GateClient, contract: str, now: datetime, notify_state: dict) -> CooldownStatus:
    state = load_cooldown_state()
    cooldown_until = _parse_datetime(state.get("cooldown_until"))
    reset_anchor_time = _parse_datetime(state.get("reset_anchor_time"))

    if cooldown_until and now < cooldown_until:
        remaining_hours = (cooldown_until - now).total_seconds() / 3600
        should_notify = not notify_state["notified"]
        if should_notify:
            notify_state["notified"] = True
            notify_state["triggered_at"] = now.isoformat()
            notify_state["notify_count"] = 1
            save_cooldown_notify_state(notify_state)

        last_loss_time = _parse_datetime(state.get("last_loss_time"))
        last_loss_str = last_loss_time.strftime('%Y-%m-%d %H:%M UTC') if last_loss_time else '未知'
        return CooldownStatus(
            triggered=True,
            reason="consecutive_loss",
            cooldown_hours=48,
            consecutive_losses=int(state.get("consecutive_losses", 0) or 0),
            last_loss_time=last_loss_time,
            can_trade_time=cooldown_until,
            should_notify=should_notify,
            details=f"连续 {int(state.get('consecutive_losses', 0) or 0)} 笔亏损，需休息 48 小时\n"
                    f"最后亏损: {last_loss_str}\n"
                    f"剩余: {remaining_hours:.1f} 小时\n"
                    f"✅ 可开单时间: {cooldown_until.strftime('%Y-%m-%d %H:%M UTC')}"
        )

    if cooldown_until and now >= cooldown_until:
        reset_cooldown_state(reset_anchor_time=cooldown_until)
        reset_cooldown_notify_state()
        state = load_cooldown_state()
        reset_anchor_time = _parse_datetime(state.get("reset_anchor_time"))

    closes = client.get_position_closes(contract, limit=30)
    if not closes:
        if notify_state["notified"]:
            reset_cooldown_notify_state()
        return CooldownStatus(triggered=False, details="无平仓记录")

    consecutive_losses = 0
    last_loss_time = None
    for close in closes:
        close_time = datetime.fromtimestamp(close['time'], tz=timezone.utc)
        if reset_anchor_time and close_time < reset_anchor_time:
            break

        pnl = close['pnl']
        if pnl < 0:
            consecutive_losses += 1
            if last_loss_time is None:
                last_loss_time = close_time
        else:
            break

    state["consecutive_losses"] = consecutive_losses
    state["last_loss_time"] = _serialize_datetime(last_loss_time)

    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES and last_loss_time:
        cooldown_until = last_loss_time + timedelta(hours=48)
        if now < cooldown_until:
            state["cooldown_until"] = _serialize_datetime(cooldown_until)
            save_cooldown_state(state)

            should_notify = not notify_state["notified"]
            if should_notify:
                notify_state["notified"] = True
                notify_state["triggered_at"] = now.isoformat()
                notify_state["notify_count"] = 1
                save_cooldown_notify_state(notify_state)

            remaining_hours = (cooldown_until - now).total_seconds() / 3600
            return CooldownStatus(
                triggered=True,
                reason="consecutive_loss",
                cooldown_hours=48,
                consecutive_losses=consecutive_losses,
                last_loss_time=last_loss_time,
                can_trade_time=cooldown_until,
                should_notify=should_notify,
                details=f"连续 {consecutive_losses} 笔亏损，需休息 48 小时\n"
                        f"最后亏损: {last_loss_time.strftime('%Y-%m-%d %H:%M UTC')}\n"
                        f"剩余: {remaining_hours:.1f} 小时\n"
                        f"✅ 可开单时间: {cooldown_until.strftime('%Y-%m-%d %H:%M UTC')}"
            )

        reset_cooldown_state(reset_anchor_time=cooldown_until)
        reset_cooldown_notify_state()
        return CooldownStatus(
            triggered=False,
            details="48 小时冷静期已结束，连续亏损计数已清零 ✅ 可以开单"
        )

    state["cooldown_until"] = None
    save_cooldown_state(state)

    if notify_state["notified"]:
        reset_cooldown_notify_state()

    return _build_consecutive_loss_status(consecutive_losses)


def load_cooldown_notify_state() -> dict:
    """加载冷静期通知状态"""
    if os.path.exists(COOLDOWN_NOTIFY_STATE_FILE):
        try:
            with open(COOLDOWN_NOTIFY_STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"notified": False, "triggered_at": None, "notify_count": 0}


def save_cooldown_notify_state(state: dict):
    """保存冷静期通知状态"""
    with open(COOLDOWN_NOTIFY_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def reset_cooldown_notify_state():
    """重置冷静期通知状态（冷静期结束时调用）"""
    save_cooldown_notify_state({"notified": False, "triggered_at": None, "notify_count": 0})


def check_cooldown(client: GateClient, contract: str = "ETH_USDT") -> CooldownStatus:
    """
    检查是否处于冷静期
    
    规则:
    1. 连续 3 笔止损亏损离场 → 强制休息 48 小时
    2. 本金 ≤ 350U → 停手 1 周
    
    返回: CooldownStatus
    """
    notify_state = load_cooldown_notify_state()
    now = datetime.now(timezone.utc)
    
    # 1. 检查本金
    try:
        account = client.get_account()
        # 熔断检查用 available + unrealised_pnl
        # available = 可用余额（扣除已占用保证金）
        # unrealised_pnl = 未实现盈亏
        # 合计反映当前真实可动用资金（包含浮盈/浮亏影响）
        equity = account.get('available', 0.0) + account.get('unrealised_pnl', 0.0)
        
        if equity <= CIRCUIT_BREAKER_EQUITY:
            can_trade_time = now + timedelta(hours=168)
            
            # 判断是否需要推送
            should_notify = not notify_state["notified"]
            if should_notify:
                notify_state["notified"] = True
                notify_state["triggered_at"] = now.isoformat()
                notify_state["notify_count"] = 1
                save_cooldown_notify_state(notify_state)
            
            return CooldownStatus(
                triggered=True,
                reason="capital_circuit_breaker",
                cooldown_hours=168,  # 1 周
                can_trade_time=can_trade_time,
                should_notify=should_notify,
                details=f"本金 {equity:.2f}U ≤ {CIRCUIT_BREAKER_EQUITY}U，停手 1 周\n"
                        f"可开单时间: {can_trade_time.strftime('%Y-%m-%d %H:%M UTC')}"
            )
    except Exception as e:
        # API 调用失败，继续检查其他条件
        equity = None
    
    # 2. 检查连续亏损
    try:
        if ENABLE_AUTO_TRADING:
            return _check_cooldown_from_state(now, notify_state)
        return _check_cooldown_from_history(client, contract, now, notify_state)
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
