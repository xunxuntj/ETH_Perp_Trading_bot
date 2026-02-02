"""交易执行器（接口封装）

实现：开仓 / 调整止损 / 平仓 的函数。实际的 HTTP 下单调用在函数中有示例但被注释掉，
默认仅返回构建好的请求体和模拟响应，防止在单元测试期间发生真实下单。

启用真实下单需显式设置环境变量 `ENABLE_REAL_TRADES=1` 并取消注释示例调用。
"""
from typing import Dict, Any, Optional
import os
import json


def _debug_print(obj: Any):
    try:
        print("[EXECUTOR DEBUG]", json.dumps(obj, default=str, ensure_ascii=False))
    except Exception:
        print("[EXECUTOR DEBUG]", obj)


def build_order_payload(direction: str, contract: str, qty: int, price: Optional[float], order_type: str = "market", reduce_only: bool = False) -> Dict[str, Any]:
    """构建下单请求体（仅用于展示/单元测试）"""
    side = "buy" if direction == "long" else "sell"
    payload = {
        "contract": contract,
        "size": qty,
        "side": side,
        "type": order_type,
        "reduce_only": reduce_only,
    }
    if price is not None and order_type != "market":
        payload["price"] = float(price)
    return payload


def open_position(client, contract: str, direction: str, qty: int, price: Optional[float] = None, stop_loss: Optional[float] = None) -> Dict[str, Any]:
    """准备并（可选地）执行开仓。

    注意：真实下单调用被注释/受 `ENABLE_REAL_TRADES` 控制。
    返回一个 dict，描述要下的单和模拟响应。
    """
    payload = build_order_payload(direction, contract, qty, price, order_type=("limit" if price else "market"))
    result = {"action": "open", "payload": payload, "executed": False, "notes": []}

    _debug_print({"prepared_order": payload})

    # 示例真实调用（注释）：
    # url_path = "/api/v4/futures/usdt/orders"
    # full_url = f"https://api.gateio.ws{url_path}"
    # body = json.dumps(payload)
    # headers = client._sign("POST", url_path, "", body)
    # resp = client.session.post(full_url, data=body, headers=headers)
    # resp.raise_for_status()
    # result["executed"] = True
    # result["response"] = resp.json()

    if os.getenv("ENABLE_REAL_TRADES") == "1":
        result["notes"].append("ENABLE_REAL_TRADES=1 set, but real HTTP call remains commented to avoid accidental trades.")
    else:
        result["notes"].append("dry-run: not sending HTTP request (set ENABLE_REAL_TRADES=1 and uncomment code to enable)")

    # If a stop_loss is provided, return suggested stop order payload
    if stop_loss is not None:
        stop_payload = {
            "contract": contract,
            "size": qty,
            "side": "sell" if direction == "long" else "buy",
            "type": "stop_market",
            "stop_price": float(stop_loss),
            "reduce_only": True
        }
        result["stop_order"] = stop_payload
        _debug_print({"prepared_stop": stop_payload})

    return result


def adjust_stop_loss(client, contract: str, position: Dict[str, Any], new_stop: float) -> Dict[str, Any]:
    """构建并（可选）执行调整止损的操作。

    由于不同平台 API 行为差异，这里返回建议的操作（如取消旧止单并创建新止单）。
    真实调用被注释。
    """
    qty = abs(position.get("size", 0))
    direction = "long" if position.get("size", 0) > 0 else "short"
    result = {"action": "adjust_stop", "executed": False}

    # 示例：取消历史止单（注释）
    # cancel_url = "/api/v4/futures/usdt/conditional_orders/{order_id}"
    # headers = client._sign("DELETE", cancel_url, "", "")
    # client.session.delete(full_cancel_url, headers=headers)

    # 创建新止单（注释）
    new_stop_payload = {
        "contract": contract,
        "size": qty,
        "side": "sell" if direction == "long" else "buy",
        "type": "stop_market",
        "stop_price": float(new_stop),
        "reduce_only": True
    }
    result["new_stop_payload"] = new_stop_payload
    _debug_print({"adjust_stop": new_stop_payload})

    if os.getenv("ENABLE_REAL_TRADES") == "1":
        result["notes"] = ["ENABLE_REAL_TRADES=1 set, but calls commented out."]
    else:
        result["notes"] = ["dry-run: not sending HTTP request"]

    return result


def close_position(client, contract: str, position: Dict[str, Any]) -> Dict[str, Any]:
    """准备并（可选）执行平仓操作。

    默认为市价减仓（reduce_only）。真实调用被注释。
    """
    qty = abs(position.get("size", 0))
    direction = "long" if position.get("size", 0) > 0 else "short"
    payload = {
        "contract": contract,
        "size": qty,
        "side": "sell" if direction == "long" else "buy",
        "type": "market",
        "reduce_only": True
    }
    result = {"action": "close", "payload": payload, "executed": False}

    _debug_print({"close_order": payload})

    # 示例真实调用（注释）
    # url_path = "/api/v4/futures/usdt/orders"
    # body = json.dumps(payload)
    # headers = client._sign("POST", url_path, "", body)
    # resp = client.session.post(f"https://api.gateio.ws{url_path}", data=body, headers=headers)
    # resp.raise_for_status()
    # result["executed"] = True
    # result["response"] = resp.json()

    if os.getenv("ENABLE_REAL_TRADES") == "1":
        result["notes"] = ["ENABLE_REAL_TRADES=1 set, but calls commented out."]
    else:
        result["notes"] = ["dry-run: not sending HTTP request"]

    return result
