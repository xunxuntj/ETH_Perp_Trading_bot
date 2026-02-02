"""
交易策略逻辑
V9.6-Exec SOP 实现
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, asdict
from enum import Enum

import pandas as pd

from config import (
    SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER, DEMA_PERIOD,
    MAX_CONSECUTIVE_LOSSES, STATE_FILE,
    LEVERAGE, CIRCUIT_BREAKER_EQUITY, get_risk_amount,
    LOCK_PROFIT_BUFFER
)
from indicators import calculate_supertrend, calculate_dema
from gate_client import GateClient


class Phase(Enum):
    """持仓阶段"""
    NONE = "none"           # 无持仓
    SURVIVAL = "survival"   # 阶段1: 生存期 (30m托管)
    LOCKED = "locked"       # 阶段2: 锁利期 (被动保本)
    HOURLY = "hourly"       # 阶段3: 换轨期 (1H托管)


class Direction(Enum):
    """方向"""
    LONG = "long"
    SHORT = "short"
    NONE = "none"


@dataclass
class Position:
    """持仓状态"""
    direction: str = "none"          # long/short/none
    entry_price: float = 0.0
    entry_time: str = ""             # ISO 格式
    size: int = 0
    stop_loss: float = 0.0
    phase: str = "none"              # survival/locked/hourly
    locked_stop: float = 0.0         # 锁利期锁定的止损价
    trade_count: int = 0             # 交易计数
    consecutive_losses: int = 0      # 连续亏损次数


@dataclass
class TradeResult:
    """交易结果"""
    action: str                      # open_long/open_short/close/adjust_sl/switch_1h/hold/none
    message: str
    details: dict = None


def load_state() -> Position:
    """加载持仓状态"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                return Position(**data)
        except:
            pass
    return Position()


def save_state(pos: Position):
    """保存持仓状态"""
    with open(STATE_FILE, 'w') as f:
        json.dump(asdict(pos), f, indent=2)


def calculate_lock_threshold(entry_price: float, qty: int, is_long: bool) -> float:
    """
    计算锁利阈值
    
    空单: 止损 ≤ 入场 - Buffer / 仓位(ETH)
    多单: 止损 ≥ 入场 + Buffer / 仓位(ETH)
    """
    position_eth = qty * 0.01
    if position_eth == 0:
        return entry_price
    
    if is_long:
        return entry_price + LOCK_PROFIT_BUFFER / position_eth
    else:
        return entry_price - LOCK_PROFIT_BUFFER / position_eth


def calculate_position_size(risk_amount: float, entry_price: float, stop_loss: float) -> dict:
    """
    计算开仓张数
    
    公式: Qty = R / |Entry - SL| / 0.01 (向下取整)
    Gate.io ETH 合约面值 = 0.01 ETH
    
    返回: {
        "qty": 张数,
        "sl_distance": 止损距离,
        "position_eth": 仓位大小(ETH),
        "position_value": 仓位价值(U),
        "margin_required": 所需保证金(U),
        "actual_risk": 实际最大亏损(U)
    }
    """
    sl_distance = abs(entry_price - stop_loss)
    if sl_distance == 0:
        return {"qty": 0, "sl_distance": 0, "position_eth": 0, 
                "position_value": 0, "margin_required": 0, "actual_risk": 0}
    
    qty = int(risk_amount / sl_distance / 0.01)  # 向下取整
    position_eth = qty * 0.01
    position_value = position_eth * entry_price
    margin_required = position_value / LEVERAGE
    actual_risk = qty * 0.01 * sl_distance
    
    return {
        "qty": qty,
        "sl_distance": sl_distance,
        "position_eth": position_eth,
        "position_value": position_value,
        "margin_required": margin_required,
        "actual_risk": actual_risk
    }


class TradingStrategy:
    def __init__(self, client: GateClient, contract: str = "ETH_USDT"):
        self.client = client
        self.contract = contract
        self.state = load_state()
    
    def analyze(self) -> TradeResult:
        """
        主分析函数
        返回交易建议
        """
        # 获取数据
        df_30m = self.client.get_candlesticks(self.contract, "30m", 300)
        df_1h = self.client.get_candlesticks(self.contract, "1h", 300)
        
        # 计算指标 (使用已收盘的K线)
        st_30m = calculate_supertrend(df_30m, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER)
        st_1h = calculate_supertrend(df_1h, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER)
        dema_1h = calculate_dema(df_1h['close'], DEMA_PERIOD)
        
        # 1H 数据 (上一根完整K线 = iloc[-2])
        last_1h_close = df_1h['close'].iloc[-2]
        last_1h_dema = dema_1h.iloc[-2]
        last_1h_dir = int(st_1h['direction'].iloc[-2])
        prev_1h_dir = int(st_1h['direction'].iloc[-3])
        last_1h_st = st_1h['supertrend'].iloc[-2]
        
        # 30m 数据 (上一根完整K线 = iloc[-2])
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_30m_st = st_30m['supertrend'].iloc[-2]
        
        current_price = df_30m['close'].iloc[-1]
        
        # 获取账户和持仓
        try:
            account = self.client.get_account()
        except:
            account = None

        try:
            position = self.client.get_positions(self.contract)
        except:
            position = None

        # 计算用于仓位/风控判断的可用本金:
        # - 默认使用 `available` (可用余额，已扣除已占用保证金)
        # - 如果当前已有持仓（全仓模式下），将 `unrealised_pnl` 加回到 available
        #   这样判断可开仓金额时能反映当前浮盈/浮亏对可动用资金的影响
        if account:
            equity = account.get('available', 0.0)
            if position is not None:
                equity += account.get('unrealised_pnl', 0.0)
        else:
            equity = 500  # 默认值（当 API 请求失败时）
        # Debug output for CI/action runs when GATE_DEBUG set
        if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
            try:
                print(f"[STRATEGY DEBUG] account={account}")
                print(f"[STRATEGY DEBUG] position={position}")
                print(f"[STRATEGY DEBUG] computed equity (available + unrealised if pos): {equity}")
            except Exception:
                pass
        
        # 风控检查
        risk = get_risk_amount(equity)
        
        if risk['status'] == 'circuit_breaker':
            return TradeResult(
                action="circuit_breaker",
                message=f"⚠️ 熔断！{risk['message']}，停手一周",
                details={"equity": equity}
            )
        
        # 通过 API 检查连续亏损（从交易历史获取）
        from cooldown import check_cooldown
        cooldown = check_cooldown(self.client, self.contract)
        
        if cooldown.triggered:
            return TradeResult(
                action="cooldown",
                message=f"⚠️ 冷静期！\n{cooldown.details}",
                details={
                    "reason": cooldown.reason,
                    "cooldown_hours": cooldown.cooldown_hours,
                    "consecutive_losses": cooldown.consecutive_losses
                }
            )
        
        risk_amount = risk['amount']
        risk_info = risk['message']
        
        # 开仓条件检查
        # 开多: 1H绿 + 价格>DEMA + 30m绿
        can_long = (last_1h_dir == 1 and 
                    last_1h_close > last_1h_dema and 
                    last_30m_dir == 1)
        
        # 开空: 1H红 + 价格<DEMA + 30m红
        can_short = (last_1h_dir == -1 and 
                     last_1h_close < last_1h_dema and 
                     last_30m_dir == -1)
        
        # 1H 刚变色？（最佳入场点标记）
        h1_just_changed = prev_1h_dir != last_1h_dir
        
        # 判断当前持仓状态
        has_position = position is not None and position['size'] != 0
        is_long = has_position and position['size'] > 0
        is_short = has_position and position['size'] < 0
        
        # 构建过滤条件检查信息（试运行调试用）- 显示真实数据
        h1_st_color = "🟢绿" if last_1h_dir == 1 else "🔴红"
        h30m_st_color = "🟢绿" if last_30m_dir == 1 else "🔴红"
        
        # 开多条件信息
        if last_1h_close > last_1h_dema:
            dema_long = f"1H收盘 {last_1h_close:.2f} > DEMA {last_1h_dema:.2f} ✅"
        else:
            dema_long = f"1H收盘 {last_1h_close:.2f} < DEMA {last_1h_dema:.2f} ❌"
        
        # 开空条件信息
        if last_1h_close < last_1h_dema:
            dema_short = f"1H收盘 {last_1h_close:.2f} < DEMA {last_1h_dema:.2f} ✅"
        else:
            dema_short = f"1H收盘 {last_1h_close:.2f} > DEMA {last_1h_dema:.2f} ❌"
        
        filter_info_long = (
            f"【过滤条件检查】\n"
            f"• 1H ST: {h1_st_color} {'✅' if last_1h_dir == 1 else '❌'}\n"
            f"• {dema_long}\n"
            f"• 30m ST: {h30m_st_color} {'✅' if last_30m_dir == 1 else '❌'}\n"
        )
        
        filter_info_short = (
            f"【过滤条件检查】\n"
            f"• 1H ST: {h1_st_color} {'✅' if last_1h_dir == -1 else '❌'}\n"
            f"• {dema_short}\n"
            f"• 30m ST: {h30m_st_color} {'✅' if last_30m_dir == -1 else '❌'}\n"
        )
        
        # ============ 无持仓: 检查开仓条件 ============
        if not has_position:
            if can_long:
                pos_info = calculate_position_size(risk_amount, current_price, last_30m_st)
                lock_threshold = calculate_lock_threshold(current_price, pos_info['qty'], is_long=True)
                timing = " ⚡最佳入场!" if h1_just_changed else ""
                
                return TradeResult(
                    action="open_long",
                    message=f"""🟢 开多信号！{timing}

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 开多 {pos_info['qty']}张 @ {current_price:.2f}
📌 设止损 @ {last_30m_st:.2f}
━━━━━━━━━━━━━━━━━━━━━━━━━

{filter_info_long}【仓位计算】
• 止损距离: {pos_info['sl_distance']:.2f}点
• 保证金: {pos_info['margin_required']:.2f}U ({LEVERAGE}x)
• 风险: {risk_info}
• 锁利阈值: {lock_threshold:.2f}""",
                    details={
                        "entry": current_price,
                        "stop_loss": last_30m_st,
                        "qty": pos_info['qty'],
                        "actual_risk": pos_info['actual_risk']
                    }
                )
            
            elif can_short:
                pos_info = calculate_position_size(risk_amount, current_price, last_30m_st)
                lock_threshold = calculate_lock_threshold(current_price, pos_info['qty'], is_long=False)
                timing = " ⚡最佳入场!" if h1_just_changed else ""
                
                return TradeResult(
                    action="open_short",
                    message=f"""🔴 开空信号！{timing}

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 开空 {pos_info['qty']}张 @ {current_price:.2f}
📌 设止损 @ {last_30m_st:.2f}
━━━━━━━━━━━━━━━━━━━━━━━━━

{filter_info_short}【仓位计算】
• 止损距离: {pos_info['sl_distance']:.2f}点
• 保证金: {pos_info['margin_required']:.2f}U ({LEVERAGE}x)
• 风险: {risk_info}
• 锁利阈值: {lock_threshold:.2f}""",
                    details={
                        "entry": current_price,
                        "stop_loss": last_30m_st,
                        "qty": pos_info['qty'],
                        "actual_risk": pos_info['actual_risk']
                    }
                )
            
            else:
                return TradeResult(
                    action="none",
                    message=f"📊 无开仓信号\n"
                            f"• 价格: {current_price:.2f}\n"
                            f"• 1H ST: {'🟢' if last_1h_dir == 1 else '🔴'}\n"
                            f"• 30m ST: {'🟢' if last_30m_dir == 1 else '🔴'}\n"
                            f"• DEMA: {last_1h_dema:.2f}\n"
                            f"• 本金: {equity:.2f}U",
                    details={"price": current_price}
                )
        
        # ============ 已持多仓 ============
        if is_long:
            # 如果满足开空条件 → 提示平多反手
            if can_short:
                pnl = (current_price - position['entry_price']) * position['size'] * 0.01
                return TradeResult(
                    action="reverse_to_short",
                    message=f"🔄 平多反手开空！\n"
                            f"• 当前多仓入场: {position['entry_price']:.2f}\n"
                            f"• 当前价: {current_price:.2f}\n"
                            f"• 预计盈亏: {pnl:.2f}U\n"
                            f"• 新空仓止损: {last_30m_st:.2f}",
                    details={"pnl": pnl, "new_stop": last_30m_st}
                )
            
            # 否则继续持有，检查止损调整
            return self._manage_long_position(
                position, df_30m, df_1h, st_30m, st_1h,
                last_1h_close, last_1h_dema, risk_amount, risk_info
            )
        
        # ============ 已持空仓 ============
        if is_short:
            # 如果满足开多条件 → 提示平空反手
            if can_long:
                pnl = (position['entry_price'] - current_price) * abs(position['size']) * 0.01
                return TradeResult(
                    action="reverse_to_long",
                    message=f"🔄 平空反手开多！\n"
                            f"• 当前空仓入场: {position['entry_price']:.2f}\n"
                            f"• 当前价: {current_price:.2f}\n"
                            f"• 预计盈亏: {pnl:.2f}U\n"
                            f"• 新多仓止损: {last_30m_st:.2f}",
                    details={"pnl": pnl, "new_stop": last_30m_st}
                )
            
            # 如果仍满足开空条件（已持空仓）→ 不提示，检查止损调整
            return self._manage_short_position(
                position, df_30m, df_1h, st_30m, st_1h,
                last_1h_close, last_1h_dema, risk_amount, risk_info
            )
        
        return TradeResult(action="none", message="未知状态")
    
    def _manage_long_position(self, position, df_30m, df_1h, st_30m, st_1h,
                               last_1h_close, last_1h_dema, risk_amount, risk_info) -> TradeResult:
        """管理多仓"""
        current_price = df_30m['close'].iloc[-1]
        entry_price = self.state.entry_price or position['entry_price']
        qty = self.state.size or abs(position['size'])
        last_30m_st = st_30m['supertrend'].iloc[-2]
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_1h_st = st_1h['supertrend'].iloc[-2]
        last_1h_dir = int(st_1h['direction'].iloc[-2])
        
        # 初始化状态
        if self.state.entry_price == 0:
            self.state.entry_price = entry_price
            self.state.size = qty
            self.state.direction = Direction.LONG.value
            self.state.entry_time = datetime.now(timezone.utc).isoformat()
            self.state.phase = Phase.SURVIVAL.value
            self.state.stop_loss = last_30m_st
            save_state(self.state)
        else:
            # 持仓状态已存在，推断当前阶段（程序重启后恢复）
            # 如果当前浮盈 > buffer，说明已超过生存期
            pnl = (current_price - entry_price) * qty * 0.01
            lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=True)

            if self.state.phase == Phase.SURVIVAL.value and pnl > LOCK_PROFIT_BUFFER:
                # 生存期但浮盈已超过buffer，判断是否应进入锁利期或换轨期
                # 检查当前1H ST是否比锁利阈值更紧（对多仓，1H ST更高表示更紧）
                if last_1h_st > lock_threshold:
                    # 1H ST更紧，直接进入换轨期
                    self.state.phase = Phase.HOURLY.value
                    self.state.locked_stop = self.state.stop_loss
                    if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                        print(f"[STRATEGY DEBUG] 持仓恢复：从生存期直接跳到换轨期 (1H ST {last_1h_st:.2f} > lock_threshold {lock_threshold:.2f})")
                else:
                    # 1H ST更松，进入锁利期
                    self.state.phase = Phase.LOCKED.value
                    self.state.locked_stop = self.state.stop_loss
                    if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                        print(f"[STRATEGY DEBUG] 持仓恢复：从生存期进入锁利期 (1H ST {last_1h_st:.2f} <= lock_threshold {lock_threshold:.2f})")
                save_state(self.state)
        
        # 判断离场信号（根据阶段看不同周期）
        exit_signal = False
                # 使用锁利阈值判断：若 1H ST 比锁利阈值更紧则直接换轨
                if last_1h_st < lock_threshold:
        
        if self.state.phase == Phase.HOURLY.value:
            # 换轨期：看 1H ST 变色
            if last_1h_dir == -1:
                        print(f"[STRATEGY DEBUG] 持仓恢复：从生存期直接跳到换轨期 (1H ST {last_1h_st:.2f} < lock_threshold {lock_threshold:.2f})")
                exit_reason = "1H ST 变红"
        else:
            # 生存期/锁利期：看 30m ST 变色
            if last_30m_dir == -1:
                exit_signal = True
                        print(f"[STRATEGY DEBUG] 持仓恢复：从生存期进入锁利期 (1H ST {last_1h_st:.2f} >= lock_threshold {lock_threshold:.2f})")
        
        if exit_signal:
            # 检查是否满足反手开空条件
            can_reverse = (last_1h_dir == -1 and 
                          last_1h_close < last_1h_dema and 
                          last_30m_dir == -1)
            
            return self._close_with_reverse_check(
                position, entry_price, current_price, 
                is_long=True, reason=exit_reason,
                can_reverse=can_reverse, reverse_direction="short",
                reverse_stop=last_30m_st, risk_amount=risk_amount, risk_info=risk_info,
                last_1h_close=last_1h_close, last_1h_dema=last_1h_dema,
                last_1h_dir=last_1h_dir, last_30m_dir=last_30m_dir
            )
        
        # 阶段管理和止损更新
        return self._update_stop_loss(entry_price, current_price, qty, last_30m_st, last_1h_st, is_long=True)
    
    def _manage_short_position(self, position, df_30m, df_1h, st_30m, st_1h,
                                last_1h_close, last_1h_dema, risk_amount, risk_info) -> TradeResult:
        """管理空仓"""
        current_price = df_30m['close'].iloc[-1]
        entry_price = self.state.entry_price or position['entry_price']
        qty = self.state.size or abs(position['size'])
        last_30m_st = st_30m['supertrend'].iloc[-2]
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_1h_st = st_1h['supertrend'].iloc[-2]
        last_1h_dir = int(st_1h['direction'].iloc[-2])
        
        # 初始化状态
        if self.state.entry_price == 0:
            self.state.entry_price = entry_price
            self.state.size = qty
            self.state.direction = Direction.SHORT.value
            self.state.entry_time = datetime.now(timezone.utc).isoformat()
            self.state.phase = Phase.SURVIVAL.value
            self.state.stop_loss = last_30m_st
            save_state(self.state)
            
            if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                print(f"[STRATEGY DEBUG] 初始化空仓: entry={entry_price:.2f}, stop_loss={last_30m_st:.2f}, qty={qty}")
        else:
            # 持仓状态已存在，推断当前阶段（程序重启后恢复）
            # 如果当前浮盈 > buffer，说明已超过生存期
            pnl = (entry_price - current_price) * qty * 0.01
            lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=False)
            
            if self.state.phase == Phase.SURVIVAL.value and pnl > LOCK_PROFIT_BUFFER:
                # 生存期但浮盈已超过buffer，判断是否应进入锁利期或换轨期
                # 检查当前1H ST是否比stop_loss更紧（对空仓，1H ST更高/松）
                if last_1h_st < self.state.stop_loss:
                    # 1H ST更紧，直接进入换轨期
                    self.state.phase = Phase.HOURLY.value
                    self.state.locked_stop = self.state.stop_loss
                    if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                        print(f"[STRATEGY DEBUG] 持仓恢复：从生存期直接跳到换轨期 (1H ST {last_1h_st:.2f} < stop {self.state.stop_loss:.2f})")
                else:
                    # 1H ST更松，进入锁利期
                    self.state.phase = Phase.LOCKED.value
                    self.state.locked_stop = self.state.stop_loss
                    if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                        print(f"[STRATEGY DEBUG] 持仓恢复：从生存期进入锁利期 (1H ST {last_1h_st:.2f} >= stop {self.state.stop_loss:.2f})")
                save_state(self.state)
        
        # 判断离场信号（根据阶段看不同周期）
        exit_signal = False
        exit_reason = ""
        
        if self.state.phase == Phase.HOURLY.value:
            # 换轨期：看 1H ST 变色
            if last_1h_dir == 1:
                exit_signal = True
                exit_reason = "1H ST 变绿"
        else:
            # 生存期/锁利期：看 30m ST 变色
            if last_30m_dir == 1:
                exit_signal = True
                exit_reason = "30m ST 变绿"
        
        if exit_signal:
            # 检查是否满足反手开多条件
            can_reverse = (last_1h_dir == 1 and 
                          last_1h_close > last_1h_dema and 
                          last_30m_dir == 1)
            
            return self._close_with_reverse_check(
                position, entry_price, current_price,
                is_long=False, reason=exit_reason,
                can_reverse=can_reverse, reverse_direction="long",
                reverse_stop=last_30m_st, risk_amount=risk_amount, risk_info=risk_info,
                last_1h_close=last_1h_close, last_1h_dema=last_1h_dema,
                last_1h_dir=last_1h_dir, last_30m_dir=last_30m_dir
            )
        
        # 阶段管理和止损更新
        return self._update_stop_loss(entry_price, current_price, qty, last_30m_st, last_1h_st, is_long=False)
        
        # 阶段管理和止损更新
        return self._update_stop_loss(entry_price, current_price, qty, last_30m_st, last_1h_st, is_long=False)
    
    def _close_with_reverse_check(self, position, entry_price, current_price, 
                                   is_long: bool, reason: str,
                                   can_reverse: bool, reverse_direction: str,
                                   reverse_stop: float, risk_amount: float, risk_info: str,
                                   last_1h_close: float, last_1h_dema: float,
                                   last_1h_dir: int, last_30m_dir: int) -> TradeResult:
        """平仓并检查反手条件"""
        qty = abs(position['size'])
        if is_long:
            pnl = (current_price - entry_price) * qty * 0.01
        else:
            pnl = (entry_price - current_price) * qty * 0.01
        
        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        
        direction = "多" if is_long else "空"
        
        # 构建平仓消息
        close_msg = (
            f"🛑 平{direction}！{reason}\n"
            f"• 入场: {entry_price:.2f}\n"
            f"• 当前: {current_price:.2f}\n"
            f"• 盈亏: {pnl:+.2f}U\n"
        )
        
        # 检查冷静期（平仓后才检查，因为这笔交易可能导致进入冷静期）
        from cooldown import check_cooldown
        cooldown = check_cooldown(self.client, self.contract)
        
        # 检查反手条件（需要同时满足技术条件 + 不在冷静期）
        if can_reverse and not cooldown.triggered:
            reverse_dir_cn = "多" if reverse_direction == "long" else "空"
            pos_info = calculate_position_size(risk_amount, current_price, reverse_stop)
            lock_threshold = calculate_lock_threshold(
                current_price, pos_info['qty'], 
                is_long=(reverse_direction == "long")
            )
            
            # 构建过滤条件信息 - 显示真实数据
            h1_st_color = "🟢绿" if last_1h_dir == 1 else "🔴红"
            h30m_st_color = "🟢绿" if last_30m_dir == 1 else "🔴红"
            
            if reverse_direction == "long":
                filter_info = (
                    f"【反手开多条件检查】\n"
                    f"• 1H ST: {h1_st_color} ✅\n"
                    f"• 1H收盘 {last_1h_close:.2f} > DEMA {last_1h_dema:.2f} ✅\n"
                    f"• 30m ST: {h30m_st_color} ✅\n"
                )
            else:
                filter_info = (
                    f"【反手开空条件检查】\n"
                    f"• 1H ST: {h1_st_color} ✅\n"
                    f"• 1H收盘 {last_1h_close:.2f} < DEMA {last_1h_dema:.2f} ✅\n"
                    f"• 30m ST: {h30m_st_color} ✅\n"
                )
            
            reverse_msg = (
                f"\n🔄 可反手开{reverse_dir_cn}！\n"
                f"{filter_info}"
                f"【开仓建议】\n"
                f"• 入场价: {current_price:.2f}\n"
                f"• 止损价: {reverse_stop:.2f} (30m ST)\n"
                f"• 止损距离: {pos_info['sl_distance']:.2f}点\n"
                f"• 张数: {pos_info['qty']}张 ({pos_info['position_eth']:.2f} ETH)\n"
                f"• 保证金: {pos_info['margin_required']:.2f}U ({LEVERAGE}x)\n"
                f"• 风险: {risk_info}\n"
                f"• 锁利阈值: {lock_threshold:.2f}"
            )
            
            self._reset_state()
            
            return TradeResult(
                action=f"close_and_reverse_{reverse_direction}",
                message=close_msg + reverse_msg,
                details={
                    "pnl": pnl, 
                    "reason": reason,
                    "reverse": True,
                    "reverse_direction": reverse_direction,
                    "reverse_stop": reverse_stop,
                    "reverse_qty": pos_info['qty']
                }
            )
        else:
            # 只平仓，不反手
            self._reset_state()
            
            # 区分不反手的原因
            if cooldown.triggered:
                no_reverse_reason = f"\n⚠️ 冷静期中，不可反手\n{cooldown.details}"
            elif not can_reverse:
                no_reverse_reason = "\n(技术条件不满足反手)"
            else:
                no_reverse_reason = ""
            
            return TradeResult(
                action="close",
                message=close_msg + no_reverse_reason,
                details={"pnl": pnl, "reason": reason, "reverse": False, "cooldown": cooldown.triggered}
            )
    
    def _close_position(self, position, entry_price, current_price, is_long: bool, reason: str) -> TradeResult:
        """平仓"""
        qty = abs(position['size'])
        if is_long:
            pnl = (current_price - entry_price) * qty * 0.01
        else:
            pnl = (entry_price - current_price) * qty * 0.01
        
        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        
        direction = "多" if is_long else "空"
        result = TradeResult(
            action="close",
            message=f"🛑 平{direction}！{reason}\n"
                    f"• 入场: {entry_price:.2f}\n"
                    f"• 当前: {current_price:.2f}\n"
                    f"• 盈亏: {pnl:+.2f}U",
            details={"pnl": pnl, "reason": reason}
        )
        self._reset_state()
        return result
    
    def _update_stop_loss(self, entry_price, current_price, qty, 
                          last_30m_st, last_1h_st, is_long: bool) -> TradeResult:
        """更新止损和阶段"""
        
        old_stop = self.state.stop_loss
        old_phase = self.state.phase
        new_stop = old_stop
        
        # 计算锁利阈值
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long)
        
        # Debug output
        if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
            print(f"[STRATEGY DEBUG] _update_stop_loss phase={old_phase}")
            print(f"[STRATEGY DEBUG]   old_stop={old_stop:.2f}, last_30m_st={last_30m_st:.2f}, last_1h_st={last_1h_st:.2f}")
            print(f"[STRATEGY DEBUG]   lock_threshold={lock_threshold:.2f}, is_long={is_long}")
            if old_phase == Phase.LOCKED.value:
                print(f"[STRATEGY DEBUG]   locked_stop={self.state.locked_stop:.2f}")
        
        # ============ 生存期 ============
        if self.state.phase == Phase.SURVIVAL.value:
            # 跟随 30m ST，只紧不松
            if is_long:

            # 检查是否换轨：1H ST 比锁利阈值更紧（使用锁利阈值判断）
            if is_long:
                if last_1h_st > lock_threshold:
                    self.state.phase = Phase.HOURLLY.value if False else Phase.HOURLY.value
                    new_stop = last_1h_st
            else:
                if last_1h_st < lock_threshold:
                    self.state.phase = Phase.HOURLY.value
                    new_stop = last_1h_st
                        if last_1h_st > self.state.locked_stop:
                            if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                                print(f"[STRATEGY DEBUG]   → 立即进入换轨期: last_1h_st {last_1h_st:.2f} > locked_stop {self.state.locked_stop:.2f}")
                            self.state.phase = Phase.HOURLY.value
                            new_stop = last_1h_st
                    else:
                        if last_1h_st < self.state.locked_stop:
                            if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                                print(f"[STRATEGY DEBUG]   → 立即进入换轨期: last_1h_st {last_1h_st:.2f} < locked_stop {self.state.locked_stop:.2f}")
                            self.state.phase = Phase.HOURLY.value
                            new_stop = last_1h_st
            else:
                new_stop = min(old_stop, last_30m_st) if old_stop > 0 else last_30m_st
                # 检查是否进入锁利期：按当前止损成交的盈利是否 > buffer
                pnl_if_stop = (entry_price - new_stop) * qty * 0.01  # 空仓盈利公式
                if pnl_if_stop > LOCK_PROFIT_BUFFER:
                    if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                        print(f"[STRATEGY DEBUG]   → 进入锁利期: 按止损{new_stop:.2f}成交盈利{pnl_if_stop:.2f}U > buffer {LOCK_PROFIT_BUFFER}U")
                    self.state.phase = Phase.LOCKED.value
                    self.state.locked_stop = new_stop
                    # 进入锁利后立即检查是否满足换轨条件：1H ST 比锁利止损更紧
                    if is_long:
                        if last_1h_st > self.state.locked_stop:
                            if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                                print(f"[STRATEGY DEBUG]   → 立即进入换轨期: last_1h_st {last_1h_st:.2f} > locked_stop {self.state.locked_stop:.2f}")
                            self.state.phase = Phase.HOURLY.value
                            new_stop = last_1h_st
                    else:
                        if last_1h_st < self.state.locked_stop:
                            if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                                print(f"[STRATEGY DEBUG]   → 立即进入换轨期: last_1h_st {last_1h_st:.2f} < locked_stop {self.state.locked_stop:.2f}")
                            self.state.phase = Phase.HOURLY.value
                            new_stop = last_1h_st
        
        # ============ 锁利期 ============
        elif self.state.phase == Phase.LOCKED.value:
            # 止损锁定不动，观察 1H ST
            new_stop = self.state.locked_stop
            
            # 检查是否换轨：1H ST 比锁利止损更紧
            if is_long:
                if last_1h_st > self.state.locked_stop:
                    self.state.phase = Phase.HOURLY.value
                    new_stop = last_1h_st
            else:
                if last_1h_st < self.state.locked_stop:
                    self.state.phase = Phase.HOURLY.value
                    new_stop = last_1h_st
        
        # ============ 换轨期 ============
        elif self.state.phase == Phase.HOURLY.value:
            # 跟随 1H ST，只紧不松
            if is_long:
                new_stop = max(old_stop, last_1h_st)
            else:
                new_stop = min(old_stop, last_1h_st)
        
        # 保存状态
        stop_changed = abs(new_stop - old_stop) > 0.01
        phase_changed = old_phase != self.state.phase
        self.state.stop_loss = new_stop
        save_state(self.state)
        
        # 计算浮盈
        if is_long:
            pnl = (current_price - entry_price) * qty * 0.01
        else:
            pnl = (entry_price - current_price) * qty * 0.01
        
        direction = "多" if is_long else "空"
        phase_names = {
            Phase.SURVIVAL.value: "🔵 生存期",
            Phase.LOCKED.value: "🟡 锁利期",
            Phase.HOURLY.value: "🟣 换轨期"
        }
        phase_exit = {
            Phase.SURVIVAL.value: "30m ST 变色",
            Phase.LOCKED.value: "30m ST 变色",
            Phase.HOURLY.value: "1H ST 变色"
        }
        
        # 返回结果
        if phase_changed:
            if self.state.phase == Phase.LOCKED.value:
                return TradeResult(
                    action="enter_locked",
                    message=f"""📍 持仓状态

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 止损锁定 @ {new_stop:.2f}
   (不再移动，保底盈利)
━━━━━━━━━━━━━━━━━━━━━━━━━

【阶段】🟡 锁利期 ⚡新进入！
【离场条件】30m ST 变{'红' if is_long else '绿'}

【持仓信息】
• 方向: {direction} | 入场: {entry_price:.2f} | 张数: {qty}张
• 当前价: {current_price:.2f} | 浮盈: {pnl:+.2f}U

【锁利触发】
• 止损 {new_stop:.2f} {'≥' if is_long else '≤'} 锁利阈值 {lock_threshold:.2f} ✅
• 保底盈利: ≥ {LOCK_PROFIT_BUFFER}U

【换轨条件】
• 1H ST {'>' if is_long else '<'} {new_stop:.2f} 时换轨""",
                    details={"phase": self.state.phase, "stop_loss": new_stop, "pnl": pnl}
                )
            elif self.state.phase == Phase.HOURLY.value:
                return TradeResult(
                    action="switch_1h",
                    message=f"""📍 持仓状态

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 止损切换 @ {new_stop:.2f} (1H ST)
━━━━━━━━━━━━━━━━━━━━━━━━━

【阶段】🟣 换轨期 ⚡新进入！
【离场条件】1H ST 变{'红' if is_long else '绿'} ← 注意变化！

【持仓信息】
• 方向: {direction} | 入场: {entry_price:.2f} | 张数: {qty}张
• 当前价: {current_price:.2f} | 浮盈: {pnl:+.2f}U

【换轨触发】
• 1H ST {new_stop:.2f} {'>' if is_long else '<'} 锁利止损 {self.state.locked_stop:.2f} ✅
• 后续跟随 1H ST，只紧不松""",
                    details={"phase": self.state.phase, "stop_loss": new_stop, "pnl": pnl}
                )
        
        if stop_changed:
            move_dir = "⬆️ 上移" if (is_long and new_stop > old_stop) or (not is_long and new_stop < old_stop) else "⬇️ 下移"
            return TradeResult(
                action="stop_updated",
                message=f"""📍 持仓状态

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 移动止损 @ {new_stop:.2f}
   (原 {old_stop:.2f} → 新 {new_stop:.2f}) {move_dir}
━━━━━━━━━━━━━━━━━━━━━━━━━

【阶段】{phase_names.get(self.state.phase)}
【离场条件】{phase_exit.get(self.state.phase)}

【持仓信息】
• 方向: {direction} | 入场: {entry_price:.2f} | 张数: {qty}张
• 当前价: {current_price:.2f} | 浮盈: {pnl:+.2f}U

【锁利进度】
• 锁利阈值: {lock_threshold:.2f}
• 距离锁利: {abs(new_stop - lock_threshold):.2f}点""",
                details={"stop_loss": new_stop, "pnl": pnl}
            )
        
        return TradeResult(
            action="hold",
            message=f"""✅ 持仓中 (无变化)
• 方向: {direction} | 阶段: {phase_names.get(self.state.phase)}
• 入场: {entry_price:.2f} | 止损: {new_stop:.2f}
• 当前价: {current_price:.2f} | 浮盈: {pnl:+.2f}U""",
            details={"pnl": pnl}
        )
    
    def _reset_state(self):
        """重置持仓状态"""
        trade_count = self.state.trade_count
        consecutive_losses = self.state.consecutive_losses
        self.state = Position()
        self.state.trade_count = trade_count
        self.state.consecutive_losses = consecutive_losses
        save_state(self.state)
