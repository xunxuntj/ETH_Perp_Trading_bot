"""
交易执行流程控制器
按照信号逻辑协调策略分析和实际交易执行
"""

from typing import Dict, Any, Optional
import os
import json

from strategy import TradingStrategy
from trading_executor import TradeExecutor
from gate_client import GateClient
from config import ENABLE_AUTO_TRADING


class ExecutionFlow:
    """完整的交易执行流程控制器"""
    
    def __init__(self, client: GateClient, contract: str = "ETH_USDT"):
        self.client = client
        self.contract = contract
        self.strategy = TradingStrategy(client, contract)
        self.executor = TradeExecutor(client, contract)
        self.verbose = os.getenv("VERBOSE", "false").lower() == "true"
    
    def log(self, message: str):
        """输出日志信息"""
        if self.verbose or os.getenv("DEBUG"):
            print(f"[FLOW] {message}")
    
    def execute_strategy_and_trade(self) -> Dict[str, Any]:
        """
        执行完整的策略分析和交易流程
        
        Returns:
            {
                "strategy_action": str,
                "trade_executed": bool,
                "trade_details": dict,
                "message": str
            }
        """
        try:
            # 第1步：分析策略信号
            self.log("开始策略分析...")
            result = self.strategy.analyze()
            
            strategy_action = result.action
            self.log(f"策略生成信号: {strategy_action}")
            
            # 第2步：根据信号执行交易
            trade_result = self._execute_by_action(strategy_action, result)
            
            return trade_result
        
        except Exception as e:
            error_msg = f"❌ 执行流程错误: {str(e)}"
            self.log(error_msg)
            
            import traceback
            traceback.print_exc()
            
            return {
                "strategy_action": "error",
                "trade_executed": False,
                "trade_details": {"error": str(e), "traceback": traceback.format_exc()},
                "message": error_msg
            }
    
    def _execute_by_action(self, action: str, strategy_result) -> Dict[str, Any]:
        """根据策略信号执行相应的交易动作"""
        
        # 无操作信号
        if action in ["none", "hold", "cooldown"]:
            return {
                "strategy_action": action,
                "trade_executed": False,
                "trade_details": strategy_result.details or {},
                "message": strategy_result.message
            }
        
        # 风控熔断
        elif action == "circuit_breaker":
            return {
                "strategy_action": action,
                "trade_executed": False,
                "trade_details": strategy_result.details or {},
                "message": strategy_result.message
            }
        
        # ============ 开仓信号 ============
        elif action == "open_long":
            return self._execute_open_long(strategy_result)
        
        elif action == "open_short":
            return self._execute_open_short(strategy_result)
        
        # ============ 平仓信号 ============
        elif action == "close":
            return self._execute_close(strategy_result)
        
        # ============ 平仓 + 反手 ============
        elif action == "close_and_reverse_long":
            return self._execute_close_and_reverse(strategy_result, "long")
        
        elif action == "close_and_reverse_short":
            return self._execute_close_and_reverse(strategy_result, "short")
        
        # ============ 反手信号（从多反空或从空反多）============
        elif action == "reverse_to_long":
            return self._execute_reverse(strategy_result, "long")
        
        elif action == "reverse_to_short":
            return self._execute_reverse(strategy_result, "short")
        
        # ============ 止损/阶段调整（持仓中）============
        elif action in ["stop_updated", "enter_locked", "switch_1h"]:
            # 这些是信息通知，不需要立即交易
            return {
                "strategy_action": action,
                "trade_executed": False,
                "trade_details": strategy_result.details or {},
                "message": strategy_result.message
            }
        
        else:
            return {
                "strategy_action": action,
                "trade_executed": False,
                "trade_details": strategy_result.details or {},
                "message": f"⚠️ 未知操作: {action}"
            }
    
    def _execute_open_long(self, strategy_result) -> Dict[str, Any]:
        """执行开多仓"""
        self.log("执行开多仓...")
        
        details = strategy_result.details or {}
        entry = details.get("entry")
        stop_loss = details.get("stop_loss")
        qty = details.get("qty")
        
        if not all([entry, stop_loss, qty]):
            return {
                "strategy_action": "open_long",
                "trade_executed": False,
                "trade_details": details,
                "message": "❌ 开多数据不完整"
            }
        
        # 执行开仓
        trade_exec = self.executor.open_long(entry, stop_loss, qty)
        
        return {
            "strategy_action": "open_long",
            "trade_executed": trade_exec["success"],
            "trade_details": {
                "executor_result": trade_exec,
                "strategy_details": details
            },
            "message": trade_exec["message"] + "\n\n" + strategy_result.message
        }
    
    def _execute_open_short(self, strategy_result) -> Dict[str, Any]:
        """执行开空仓"""
        self.log("执行开空仓...")
        
        details = strategy_result.details or {}
        entry = details.get("entry")
        stop_loss = details.get("stop_loss")
        qty = details.get("qty")
        
        if not all([entry, stop_loss, qty]):
            return {
                "strategy_action": "open_short",
                "trade_executed": False,
                "trade_details": details,
                "message": "❌ 开空数据不完整"
            }
        
        # 执行开仓
        trade_exec = self.executor.open_short(entry, stop_loss, qty)
        
        return {
            "strategy_action": "open_short",
            "trade_executed": trade_exec["success"],
            "trade_details": {
                "executor_result": trade_exec,
                "strategy_details": details
            },
            "message": trade_exec["message"] + "\n\n" + strategy_result.message
        }
    
    def _execute_close(self, strategy_result) -> Dict[str, Any]:
        """执行平仓（不反手）"""
        self.log("执行平仓...")
        
        details = strategy_result.details or {}
        pnl = details.get("pnl", 0)
        reason = details.get("reason", "signal")
        
        # 从持仓信息获取方向和数量
        position = self.client.get_positions(self.contract)
        if not position:
            return {
                "strategy_action": "close",
                "trade_executed": False,
                "trade_details": details,
                "message": "⚠️ 没有持仓"
            }
        
        qty = abs(position.get("size", 0))
        direction = "long" if position["size"] > 0 else "short"
        
        # 执行平仓
        trade_exec = self.executor.close_position(direction, qty, pnl, reason)
        
        return {
            "strategy_action": "close",
            "trade_executed": trade_exec["success"],
            "trade_details": {
                "executor_result": trade_exec,
                "strategy_details": details
            },
            "message": trade_exec["message"] + "\n\n" + strategy_result.message
        }
    
    def _execute_close_and_reverse(self, strategy_result, reverse_direction: str) -> Dict[str, Any]:
        """执行平仓并反手"""
        self.log(f"执行平仓并反手到{reverse_direction}...")
        
        details = strategy_result.details or {}
        pnl = details.get("pnl", 0)
        reason = details.get("reason", "signal")
        reverse_stop = details.get("reverse_stop", 0)
        reverse_qty = details.get("reverse_qty", 0)
        
        # 获取当前持仓
        position = self.client.get_positions(self.contract)
        if not position:
            return {
                "strategy_action": f"close_and_reverse_{reverse_direction}",
                "trade_executed": False,
                "trade_details": details,
                "message": "⚠️ 没有持仓"
            }
        
        qty = abs(position.get("size", 0))
        current_direction = "long" if position["size"] > 0 else "short"
        current_price = self.client.get_ticker(self.contract)["last"]
        
        # 第1步：平仓
        close_exec = self.executor.close_position(current_direction, qty, pnl, reason)
        
        if not close_exec["success"]:
            return {
                "strategy_action": f"close_and_reverse_{reverse_direction}",
                "trade_executed": False,
                "trade_details": {
                    "close_result": close_exec,
                    "strategy_details": details
                },
                "message": close_exec["message"]
            }
        
        # 第2步：反手开仓
        if reverse_direction == "long":
            reverse_exec = self.executor.open_long(current_price, reverse_stop, reverse_qty)
        else:
            reverse_exec = self.executor.open_short(current_price, reverse_stop, reverse_qty)
        
        combined_msg = close_exec["message"] + "\n\n" + reverse_exec["message"]
        
        return {
            "strategy_action": f"close_and_reverse_{reverse_direction}",
            "trade_executed": close_exec["success"] and reverse_exec["success"],
            "trade_details": {
                "close_result": close_exec,
                "reverse_result": reverse_exec,
                "strategy_details": details
            },
            "message": combined_msg + "\n\n" + strategy_result.message
        }
    
    def _execute_reverse(self, strategy_result, new_direction: str) -> Dict[str, Any]:
        """执行反手建议（仅提示，不自动执行）"""
        self.log(f"反手建议: {new_direction}")
        
        details = strategy_result.details or {}
        
        return {
            "strategy_action": f"reverse_to_{new_direction}",
            "trade_executed": False,
            "trade_details": details,
            "message": strategy_result.message + "\n\n⚠️ 这是反手建议，需要手动确认执行"
        }
    
    def get_execution_log(self) -> list:
        """获取完整的执行日志"""
        return self.executor.get_trade_log()
    
    def save_execution_log(self, filepath: str = "execution_log.json"):
        """保存执行日志"""
        self.executor.save_trade_log(filepath)
