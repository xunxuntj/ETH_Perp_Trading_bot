"""交易执行器：封装下单/调止损/平仓逻辑

实现原则：
- 当 `config.ENABLE_AUTO_TRADING` 为 False 时，仅返回模拟结果（不发起网络请求）
- 支持在开启时执行真实请求（代码中执行调用已用注释标注，默认保留注释以便单元测试安全）
"""
from typing import Dict, Any
import time
import json
import os

from gate_client import GateClient
import config


class TradingExecutor:
    def __init__(self, client: GateClient):
        self.client = client

    def _simulate_response(self, action: str, details: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ok": True,
            "action": action,
            "time": int(time.time()),
            "details": details
        }

    def open_position(self, contract: str, side: str, qty: int, price: float = None) -> Dict[str, Any]:
        """开仓（市价/限价由 caller 决定）。

        side: 'long' or 'short'
        qty: 合约张数（整数）
        price: 可选限价价位；None 表示市价
        """
        details = {"contract": contract, "side": side, "qty": qty, "price": price}

        if not config.ENABLE_AUTO_TRADING:
            # 不执行真实交易，仅提示
            return {"executed": False, "reason": "dry_run", "payload": details}

        # 以下为真实下单示例（注：已注释，启用请取消注释并确保 GateClient 可下单）
        # url = f"https://api.gateio.ws/api/v4/futures/usdt/orders"
        # body = json.dumps({
        #     "contract": contract,
        #     "size": qty,
        #     "price": price or "market",
        #     "reduce_only": False,
        #     "side": "sell" if side == "short" else "buy",
        #     "time_in_force": "ioc" if price is None else "gtc"
        # })
        # headers = self.client._sign("POST", "/api/v4/futures/usdt/orders", "", body)
        # resp = self.client.session.post(url, data=body, headers=headers)
        # resp.raise_for_status()
        # return resp.json()

        # 目前返回模拟成功结果
        return {"executed": True, "result": self._simulate_response("open", details)}

    def adjust_stop(self, contract: str, side: str, qty: int, new_stop: float) -> Dict[str, Any]:
        """调节止损（通常实现为修改条件单或追加止损单）。

        这里用简化逻辑：实际交易所 API 调用请在生产环境中实现。
        """
        details = {"contract": contract, "side": side, "qty": qty, "new_stop": new_stop}

        if not config.ENABLE_AUTO_TRADING:
            return {"executed": False, "reason": "dry_run", "payload": details}

        # 示例（注释掉真实调用）
        # url = f"https://api.gateio.ws/api/v4/futures/usdt/conditional_orders"
        # body = json.dumps({ ... })
        # headers = self.client._sign("POST", "/api/v4/futures/usdt/conditional_orders", "", body)
        # resp = self.client.session.post(url, data=body, headers=headers)
        # resp.raise_for_status()

        return {"executed": True, "result": self._simulate_response("adjust_stop", details)}

    def close_position(self, contract: str, side: str, qty: int) -> Dict[str, Any]:
        """平仓：发送市价单平掉指定数量"""
        details = {"contract": contract, "side": side, "qty": qty}

        if not config.ENABLE_AUTO_TRADING:
            return {"executed": False, "reason": "dry_run", "payload": details}

        # 真实下市价单的示例（注释）
        # url = f"https://api.gateio.ws/api/v4/futures/usdt/orders"
        # body = json.dumps({"contract": contract, "size": qty, "price": "market", "side": "buy" if side=="short" else "sell"})
        # headers = self.client._sign("POST", "/api/v4/futures/usdt/orders", "", body)
        # resp = self.client.session.post(url, data=body, headers=headers)
        # resp.raise_for_status()

        return {"executed": True, "result": self._simulate_response("close", details)}
"""
自动化交易执行器
处理：开仓、调整止损、平仓

实际的 API 调用被注释，防止误操作。单元测试时在 dry_run=True 模式运行。
启用真实交易需取消注释并手动启用。
"""

import os
from typing import Optional, Dict, Any


class TradeExecutor:
    """交易执行器 - 单独模块，便于单元测试和二次开发"""

    def __init__(self, gate_client, contract: str = "ETH_USDT", dry_run: bool = False):
        """
        初始化交易执行器
        
        Args:
            gate_client: Gate.io API 客户端
            contract: 交易合约（如 "ETH_USDT"）
            dry_run: True 时不执行真实交易，仅返回模拟结果
        """
        self.client = gate_client
        self.contract = contract
        self.dry_run = dry_run

    def open_position(self, direction: str, entry_price: float, stop_loss: float, 
                      qty: int) -> Dict[str, Any]:
        """
        开仓
        
        Args:
            direction: "long" 或 "short"
            entry_price: 入场价格
            stop_loss: 止损价格
            qty: 张数
        
        Returns:
            {
                "success": bool,
                "message": str,
                "order_id": Optional[str],
                "order_info": Optional[dict]
            }
        """
        if qty <= 0:
            return {
                "success": False,
                "message": f"张数必须 > 0，当前: {qty}",
                "order_id": None,
                "order_info": None
            }

        text = f"开{'多' if direction == 'long' else '空'} @ {entry_price:.2f}，SL @ {stop_loss:.2f}，{qty}张"
        
        if self.dry_run or os.getenv("DRY_RUN"):
            return {
                "success": True,
                "message": f"[模拟] {text}",
                "order_id": f"sim_{direction}_{int(entry_price * 100)}",
                "order_info": {
                    "contract": self.contract,
                    "direction": direction,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "qty": qty
                }
            }
        
        try:
            # ⚠️ 实际交易调用（默认注释，需手动启用）
            # result = self.client.create_order(...)
            return {
                "success": True,
                "message": f"{text} - [交易调用已注释，请启用实际 API]",
                "order_id": None,
                "order_info": None
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"开仓失败: {str(e)}",
                "order_id": None,
                "order_info": None
            }

    def adjust_stop_loss(self, direction: str, current_stop: float, new_stop: float) -> Dict[str, Any]:
        """
        调整止损
        
        Args:
            direction: "long" 或 "short"
            current_stop: 当前止损价格
            new_stop: 新止损价格
        
        Returns:
            {
                "success": bool,
                "message": str,
                "order_id": Optional[str],
                "order_info": Optional[dict]
            }
        """
        if direction == "long":
            if new_stop <= current_stop:
                return {
                    "success": False,
                    "message": f"多仓止损只能上移，当前 {current_stop:.2f} >= 新止损 {new_stop:.2f}",
                    "order_id": None,
                    "order_info": None
                }
        else:  # short
            if new_stop >= current_stop:
                return {
                    "success": False,
                    "message": f"空仓止损只能下移，当前 {current_stop:.2f} <= 新止损 {new_stop:.2f}",
                    "order_id": None,
                    "order_info": None
                }

        text = f"调整{'多' if direction == 'long' else '空'}仓止损: {current_stop:.2f} → {new_stop:.2f}"

        if self.dry_run or os.getenv("DRY_RUN"):
            return {
                "success": True,
                "message": f"[模拟] {text}",
                "order_id": f"sim_sl_{int(new_stop * 100)}",
                "order_info": {
                    "current_stop": current_stop,
                    "new_stop": new_stop,
                    "direction": direction
                }
            }

        try:
            # ⚠️ 实际交易调用（默认注释）
            # self.client.cancel_orders(contract=self.contract, text="stop_loss")
            return {
                "success": True,
                "message": f"{text} - [交易调用已注释，请启用实际 API]",
                "order_id": None,
                "order_info": None
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"调整止损失败: {str(e)}",
                "order_id": None,
                "order_info": None
            }

    def close_position(self, direction: str, qty: int, exit_price: Optional[float] = None) -> Dict[str, Any]:
        """
        平仓
        
        Args:
            direction: "long" 或 "short"
            qty: 张数
            exit_price: 平仓价格（可选，不指定时执行市价平仓）
        
        Returns:
            {
                "success": bool,
                "message": str,
                "order_id": Optional[str],
                "order_info": Optional[dict]
            }
        """
        if qty <= 0:
            return {
                "success": False,
                "message": f"张数必须 > 0，当前: {qty}",
                "order_id": None,
                "order_info": None
            }

        price_str = f" @ {exit_price:.2f}" if exit_price else " (市价)"
        text = f"平{'多' if direction == 'long' else '空'} {qty}张{price_str}"

        if self.dry_run or os.getenv("DRY_RUN"):
            return {
                "success": True,
                "message": f"[模拟] {text}",
                "order_id": f"sim_close_{int(exit_price * 100) if exit_price else 0}",
                "order_info": {
                    "direction": direction,
                    "qty": qty,
                    "exit_price": exit_price
                }
            }

        try:
            # ⚠️ 实际交易调用（默认注释）
            # close_order = self.client.create_order(...)
            return {
                "success": True,
                "message": f"{text} - [交易调用已注释，请启用实际 API]",
                "order_id": None,
                "order_info": None
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"平仓失败: {str(e)}",
                "order_id": None,
                "order_info": None
            }
