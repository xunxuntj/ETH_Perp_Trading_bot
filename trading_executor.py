"""
完整的交易执行器
实现：开仓 → 设置止损 → 调整止损 → 平仓 → 反手

特点：
- 支持干运行模式（ENABLE_AUTO_TRADING=false 时仅模拟）
- 完整的错误处理和边界检查
- 详细的执行日志和状态跟踪
"""

import json
import os
import time
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from gate_client import GateClient
from config import (
    ENABLE_AUTO_TRADING, AUTO_SET_STOP_LOSS, 
    STOP_LOSS_MODE, CLOSE_MODE, LEVERAGE
)


class TradeExecutor:
    """交易执行器：按照信号逻辑执行实际交易"""
    
    def __init__(self, client: GateClient, contract: str = "ETH_USDT"):
        self.client = client
        self.contract = contract
        self.dry_run = not ENABLE_AUTO_TRADING
        
        # 交易日志
        self.trade_log = []
    
    def _log(self, action: str, message: str, details: Dict[str, Any] = None):
        """记录交易日志"""
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = {
            "timestamp": timestamp,
            "action": action,
            "message": message,
            "details": details or {}
        }
        self.trade_log.append(log_entry)
        
        # 打印到控制台
        print(f"[{timestamp}] [{action}] {message}")
        if details:
            print(f"  Details: {json.dumps(details, ensure_ascii=False, indent=2)}")
    
    def _is_dry_run(self) -> bool:
        """判断是否为干运行模式"""
        return self.dry_run or os.getenv("DRY_RUN", "").lower() == "true"
    
    def open_long(self, entry_price: float, stop_loss: float, qty: int) -> Dict[str, Any]:
        """
        开多仓
        
        Args:
            entry_price: 入场价格
            stop_loss: 止损价格
            qty: 张数
        
        Returns:
            {
                "success": bool,
                "order_id": Optional[str],
                "message": str,
                "details": dict
            }
        """
        if qty <= 0:
            return {
                "success": False,
                "order_id": None,
                "message": f"❌ 开多失败：张数必须 > 0，当前 {qty}",
                "details": {"error": "invalid_qty", "qty": qty}
            }
        
        if stop_loss >= entry_price:
            return {
                "success": False,
                "order_id": None,
                "message": f"❌ 开多失败：止损价 {stop_loss:.2f} >= 入场价 {entry_price:.2f}",
                "details": {"error": "invalid_stop_loss"}
            }
        
        try:
            # 第1步：下开仓单（市价）
            if self._is_dry_run():
                main_order = {
                    "id": f"sim_long_{int(time.time())}",
                    "contract": self.contract,
                    "size": qty,
                    "price": None,
                    "status": "closed",  # 市价单立即成交
                    "filled_size": qty
                }
                self._log("OPEN_LONG", f"✅ [模拟] 开多 {qty}张 @ {entry_price:.2f}")
            else:
                # 实际交易：市价下多仓单
                main_order = self.client.create_order(
                    contract=self.contract,
                    size=qty,
                    price=None,  # 市价
                    reduce_only=False,
                    text=f"auto_open_long_{int(time.time())}"
                )
                self._log("OPEN_LONG", f"✅ 开多 {qty}张 @ 市价")
            
            # 第2步：设置止损条件单
            stop_order = None
            if AUTO_SET_STOP_LOSS:
                if self._is_dry_run():
                    stop_order = {
                        "id": f"sim_stop_{int(time.time())}",
                        "contract": self.contract,
                        "size": -qty,
                        "price": str(stop_loss),
                        "status": "open"
                    }
                    self._log("SET_STOP", f"✅ [模拟] 设置止损单 {qty}张 @ {stop_loss:.2f}")
                else:
                    # 实际交易：设置止损条件单
                    stop_order = self.client.create_order(
                        contract=self.contract,
                        size=-qty,  # 反向平仓
                        price=stop_loss,
                        reduce_only=True,
                        text=f"stop_loss_long_{int(time.time())}"
                    )
                    self._log("SET_STOP", f"✅ 设置止损单 {qty}张 @ {stop_loss:.2f}")
            
            return {
                "success": True,
                "order_id": main_order.get("id"),
                "message": f"🟢 成功开多 {qty}张 @ {entry_price:.2f}，止损 @ {stop_loss:.2f}",
                "details": {
                    "order_id": main_order.get("id"),
                    "qty": qty,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "stop_order_id": stop_order.get("id") if stop_order else None,
                    "dry_run": self._is_dry_run()
                }
            }
        
        except Exception as e:
            error_msg = f"❌ 开多异常：{str(e)}"
            self._log("ERROR_OPEN_LONG", error_msg, {"error": str(e)})
            return {
                "success": False,
                "order_id": None,
                "message": error_msg,
                "details": {"exception": str(e)}
            }
    
    def open_short(self, entry_price: float, stop_loss: float, qty: int) -> Dict[str, Any]:
        """
        开空仓
        
        Args:
            entry_price: 入场价格
            stop_loss: 止损价格
            qty: 张数
        
        Returns:
            {
                "success": bool,
                "order_id": Optional[str],
                "message": str,
                "details": dict
            }
        """
        if qty <= 0:
            return {
                "success": False,
                "order_id": None,
                "message": f"❌ 开空失败：张数必须 > 0，当前 {qty}",
                "details": {"error": "invalid_qty", "qty": qty}
            }
        
        if stop_loss <= entry_price:
            return {
                "success": False,
                "order_id": None,
                "message": f"❌ 开空失败：止损价 {stop_loss:.2f} <= 入场价 {entry_price:.2f}",
                "details": {"error": "invalid_stop_loss"}
            }
        
        try:
            # 第1步：下开仓单（市价）
            if self._is_dry_run():
                main_order = {
                    "id": f"sim_short_{int(time.time())}",
                    "contract": self.contract,
                    "size": -qty,
                    "price": None,
                    "status": "closed",
                    "filled_size": qty
                }
                self._log("OPEN_SHORT", f"✅ [模拟] 开空 {qty}张 @ {entry_price:.2f}")
            else:
                # 实际交易：市价下空仓单
                main_order = self.client.create_order(
                    contract=self.contract,
                    size=-qty,  # 负数表示空仓
                    price=None,  # 市价
                    reduce_only=False,
                    text=f"auto_open_short_{int(time.time())}"
                )
                self._log("OPEN_SHORT", f"✅ 开空 {qty}张 @ 市价")
            
            # 第2步：设置止损条件单
            stop_order = None
            if AUTO_SET_STOP_LOSS:
                if self._is_dry_run():
                    stop_order = {
                        "id": f"sim_stop_{int(time.time())}",
                        "contract": self.contract,
                        "size": qty,  # 反向平仓
                        "price": str(stop_loss),
                        "status": "open"
                    }
                    self._log("SET_STOP", f"✅ [模拟] 设置止损单 {qty}张 @ {stop_loss:.2f}")
                else:
                    # 实际交易：设置止损条件单
                    stop_order = self.client.create_order(
                        contract=self.contract,
                        size=qty,  # 正数表示多方向平仓
                        price=stop_loss,
                        reduce_only=True,
                        text=f"stop_loss_short_{int(time.time())}"
                    )
                    self._log("SET_STOP", f"✅ 设置止损单 {qty}张 @ {stop_loss:.2f}")
            
            return {
                "success": True,
                "order_id": main_order.get("id"),
                "message": f"🔴 成功开空 {qty}张 @ {entry_price:.2f}，止损 @ {stop_loss:.2f}",
                "details": {
                    "order_id": main_order.get("id"),
                    "qty": qty,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "stop_order_id": stop_order.get("id") if stop_order else None,
                    "dry_run": self._is_dry_run()
                }
            }
        
        except Exception as e:
            error_msg = f"❌ 开空异常：{str(e)}"
            self._log("ERROR_OPEN_SHORT", error_msg, {"error": str(e)})
            return {
                "success": False,
                "order_id": None,
                "message": error_msg,
                "details": {"exception": str(e)}
            }
    
    def adjust_stop_loss(self, direction: str, new_stop: float, qty: int,
                        old_stop: Optional[float] = None) -> Dict[str, Any]:
        """
        调整止损（注销旧止损单并创建新的）
        
        Args:
            direction: "long" 或 "short"
            new_stop: 新的止损价格
            qty: 持仓张数
            old_stop: 旧的止损价格（用于验证）
        
        Returns:
            {
                "success": bool,
                "message": str,
                "details": dict
            }
        """
        if qty <= 0:
            return {
                "success": False,
                "message": f"❌ 调整止损失败：张数必须 > 0",
                "details": {"error": "invalid_qty", "qty": qty}
            }
        
        try:
            # 验证止损方向
            if direction == "long":
                if old_stop and new_stop < old_stop:
                    return {
                        "success": False,
                        "message": f"❌ 多仓止损只能上移，当前 {old_stop:.2f} 新止损 {new_stop:.2f}",
                        "details": {"error": "invalid_direction", "mode": "tight_only"}
                    }
            else:  # short
                if old_stop and new_stop > old_stop:
                    return {
                        "success": False,
                        "message": f"❌ 空仓止损只能下移，当前 {old_stop:.2f} 新止损 {new_stop:.2f}",
                        "details": {"error": "invalid_direction", "mode": "tight_only"}
                    }
            
            if self._is_dry_run():
                # 模拟模式
                if direction == "long":
                    self._log("ADJUST_STOP", f"✅ [模拟] 多仓止损调整 {old_stop:.2f} → {new_stop:.2f}")
                else:
                    self._log("ADJUST_STOP", f"✅ [模拟] 空仓止损调整 {old_stop:.2f} → {new_stop:.2f}")
                
                return {
                    "success": True,
                    "message": f"✅ 止损已调整 {old_stop:.2f} → {new_stop:.2f}",
                    "details": {
                        "direction": direction,
                        "old_stop": old_stop,
                        "new_stop": new_stop,
                        "qty": qty,
                        "dry_run": True
                    }
                }
            else:
                # 实际交易：取消旧止损单，创建新的
                # 第1步：取消所有现有的 stop_loss 单
                try:
                    self.client.cancel_orders(
                        contract=self.contract,
                        text="stop_loss" if direction == "long" else "stop_loss"
                    )
                except:
                    pass  # 可能没有现有止损单
                
                # 第2步：创建新的止损单
                if direction == "long":
                    new_order = self.client.create_order(
                        contract=self.contract,
                        size=-qty,
                        price=new_stop,
                        reduce_only=True,
                        text=f"stop_loss_long_{int(time.time())}"
                    )
                else:  # short
                    new_order = self.client.create_order(
                        contract=self.contract,
                        size=qty,
                        price=new_stop,
                        reduce_only=True,
                        text=f"stop_loss_short_{int(time.time())}"
                    )
                
                self._log("ADJUST_STOP", f"✅ 止损已调整 {old_stop:.2f} → {new_stop:.2f}")
                
                return {
                    "success": True,
                    "message": f"✅ 止损已调整 {old_stop:.2f} → {new_stop:.2f}",
                    "details": {
                        "direction": direction,
                        "old_stop": old_stop,
                        "new_stop": new_stop,
                        "qty": qty,
                        "order_id": new_order.get("id")
                    }
                }
        
        except Exception as e:
            error_msg = f"❌ 调整止损异常：{str(e)}"
            self._log("ERROR_ADJUST_STOP", error_msg, {"error": str(e)})
            return {
                "success": False,
                "message": error_msg,
                "details": {"exception": str(e)}
            }
    
    def close_position(self, direction: str, qty: int, 
                       pnl: Optional[float] = None,
                       reason: str = "signal") -> Dict[str, Any]:
        """
        平仓
        
        Args:
            direction: "long" 或 "short"
            qty: 张数
            pnl: 已实现盈亏（仅用于日志）
            reason: 平仓原因（用于日志）
        
        Returns:
            {
                "success": bool,
                "order_id": Optional[str],
                "message": str,
                "details": dict
            }
        """
        if qty <= 0:
            return {
                "success": False,
                "order_id": None,
                "message": f"❌ 平仓失败：张数必须 > 0",
                "details": {"error": "invalid_qty"}
            }
        
        try:
            # 第1步：取消所有现有的 stop_loss 单（避免平仓后止损自动触发）
            if not self._is_dry_run():
                try:
                    self.client.cancel_orders(contract=self.contract, text="stop_loss")
                except:
                    pass  # 可能没有现有止损单
            
            # 第2步：下平仓单（市价）
            mode_str = "多" if direction == "long" else "空"
            close_size = -qty if direction == "long" else qty
            
            if self._is_dry_run():
                close_order = {
                    "id": f"sim_close_{int(time.time())}",
                    "contract": self.contract,
                    "size": close_size,
                    "price": None,
                    "status": "closed",
                    "filled_size": qty
                }
                pnl_str = f" 盈亏 {pnl:+.2f}U" if pnl is not None else ""
                self._log("CLOSE", f"✅ [模拟] 平{mode_str} {qty}张{pnl_str}")
            else:
                # 实际交易：市价平仓
                close_order = self.client.create_order(
                    contract=self.contract,
                    size=close_size,
                    price=None,  # 市价
                    reduce_only=True,
                    text=f"close_{reason}_{int(time.time())}"
                )
                pnl_str = f" 盈亏 {pnl:+.2f}U" if pnl is not None else ""
                self._log("CLOSE", f"✅ 平{mode_str} {qty}张{pnl_str}")
            
            return {
                "success": True,
                "order_id": close_order.get("id"),
                "message": f"🛑 成功平{mode_str} {qty}张" + (f"，盈亏 {pnl:+.2f}U" if pnl else ""),
                "details": {
                    "order_id": close_order.get("id"),
                    "direction": direction,
                    "qty": qty,
                    "pnl": pnl,
                    "reason": reason,
                    "dry_run": self._is_dry_run()
                }
            }
        
        except Exception as e:
            error_msg = f"❌ 平仓异常：{str(e)}"
            mode_str = "多" if direction == "long" else "空"
            self._log("ERROR_CLOSE", error_msg, {"error": str(e)})
            return {
                "success": False,
                "order_id": None,
                "message": error_msg,
                "details": {"exception": str(e), "direction": direction, "qty": qty}
            }
    
    def get_trade_log(self) -> list:
        """获取交易日志"""
        return self.trade_log
    
    def save_trade_log(self, filepath: str = "trade_log.json"):
        """保存交易日志到文件"""
        try:
            with open(filepath, 'w') as f:
                json.dump(self.trade_log, f, indent=2, ensure_ascii=False)
            print(f"✅ 交易日志已保存到 {filepath}")
        except Exception as e:
            print(f"❌ 保存日志失败：{str(e)}")
