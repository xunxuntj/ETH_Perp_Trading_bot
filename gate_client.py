"""
Gate.io API 客户端
获取 K线数据和持仓信息
"""

import time
import hashlib
import hmac
import requests
import json
from typing import Optional
import pandas as pd
import os

BASE_URL = "https://api.gateio.ws/api/v4"


class GateClient:
    def __init__(self, api_key: str = "", api_secret: str = "", debug: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        # Enable debug if parameter True or environment variable GATE_DEBUG is set
        gate_debug = os.getenv('GATE_DEBUG', '').lower()
        self.debug = bool(debug or (gate_debug not in ('', '0', 'false', 'no', 'off')))
    
    def _clean_text(self, text: str) -> str:
        """
        格式化备注信息以符合 Gate.io API 规范：
        1. 必须以 't-' 开头。
        2. 去除 't-' 后长度不能超过 28 字节。
        3. 只允许字母、数字、下划线、连字符和点号。
        """
        if not text:
            return ""
        
        import re
        if text.startswith("t-"):
            content = text[2:]
        else:
            content = text
            
        # 仅保留合法字符 (a-zA-Z0-9_.-)
        content = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", content)
        
        # 截断超出部分（28字节）
        encoded = content.encode("utf-8")
        if len(encoded) > 28:
            content = encoded[:28].decode("utf-8", errors="ignore")
            
        return "t-" + content

    def _sign(self, method: str, url: str, query_string: str = "", body: str = "") -> dict:
        """生成签名请求头"""
        t = str(int(time.time()))
        hashed_body = hashlib.sha512(body.encode()).hexdigest()
        
        s = f"{method}\n{url}\n{query_string}\n{hashed_body}\n{t}"
        sign = hmac.new(
            self.api_secret.encode(), 
            s.encode(), 
            hashlib.sha512
        ).hexdigest()
        
        return {
            "KEY": self.api_key,
            "Timestamp": t,
            "SIGN": sign,
            "Content-Type": "application/json",
            "X-Gate-Size-Decimal": "1"
        }

    
    def get_candlesticks(self, contract: str, interval: str = "30m", limit: int = 300) -> pd.DataFrame:
        """
        获取合约 K 线数据
        interval: 1m, 5m, 15m, 30m, 1h, 4h, 1d
        """
        url = f"{BASE_URL}/futures/usdt/candlesticks"
        params = {
            "contract": contract,
            "interval": interval,
            "limit": limit
        }
        
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        # Gate.io 返回: [{t, o, h, l, c, v, sum}, ...]
        df = pd.DataFrame(data)
        df = df.rename(columns={
            't': 'timestamp',
            'o': 'open',
            'h': 'high', 
            'l': 'low',
            'c': 'close',
            'v': 'volume'
        })
        
        df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='s')
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        
        df = df.sort_values('timestamp').reset_index(drop=True)
        df.set_index('timestamp', inplace=True)
        
        return df
    
    def get_positions(self, contract: str) -> Optional[dict]:
        """获取当前持仓"""
        url_path = f"/api/v4/futures/usdt/positions/{contract}"
        full_url = f"{BASE_URL}/futures/usdt/positions/{contract}"
        
        headers = self._sign("GET", url_path, "", "")
        resp = self.session.get(full_url, headers=headers)
        if self.debug:
            try:
                print(f"[GATE DEBUG] GET {full_url} status={resp.status_code} text={resp.text[:1000]}")
            except Exception:
                pass
        
        if resp.status_code == 404:
            return None
        
        resp.raise_for_status()
        data = resp.json()
        
        # 无持仓返回 size=0
        try:
            size_val = float(data.get('size', 0))
        except (ValueError, TypeError):
            size_val = 0.0
            
        if size_val == 0:
            return None
        
        return {
            'size': int(size_val),  # 正=多, 负=空
            'entry_price': float(data['entry_price']),
            'mark_price': float(data['mark_price']),
            'liq_price': float(data['liq_price']) if data.get('liq_price') else None,
            'unrealised_pnl': float(data.get('unrealised_pnl', 0)),
            'leverage': int(data.get('leverage', 1)),
            'margin': float(data.get('margin', 0))
        }
    
    def get_account(self) -> dict:
        """
        获取账户信息
        
        【关键信息】：
        API返回的字段（Gate.io全仓模式）:
        - cross_available: 全仓可用余额（全仓账户的关键字段）
        - available: 隔离仓可用余额
        - total: 账户总资金
        
        【优先级】: cross_available > available > total
        脚本会自动选择最合适的字段作为账户本金
        
        【调试】:
        设置 DEBUG=1 环境变量可看完整账户数据输出
        """
        url_path = "/api/v4/futures/usdt/accounts"
        full_url = f"{BASE_URL}/futures/usdt/accounts"
        
        headers = self._sign("GET", url_path, "", "")
        resp = self.session.get(full_url, headers=headers)
        # Debug: print request/response info to trace behavior in CI/actions
        if self.debug:
            try:
                text = resp.text
            except Exception:
                text = '<no-text>'
            # mask sensitive header values for printing
            masked_headers = headers.copy()
            if 'KEY' in masked_headers and masked_headers['KEY']:
                masked_headers['KEY'] = masked_headers['KEY'][:4] + '...'
            if 'SIGN' in masked_headers and masked_headers['SIGN']:
                masked_headers['SIGN'] = masked_headers['SIGN'][:6] + '...'
            print(f"[GATE DEBUG] GET {full_url} headers={masked_headers} status={resp.status_code}")
            print(f"[GATE DEBUG] resp.text (first 1000 chars): {text[:1000]}")

        resp.raise_for_status()

        try:
            data = resp.json()
            # 总是打印原始数据，便于诊断
            import sys
            print(f"[GATE RAW ACCOUNT] {data}", file=sys.stderr)
        except Exception as e:
            # If JSON decoding fails, log raw text for debugging and re-raise
            if self.debug:
                print(f"[GATE DEBUG] Failed to parse JSON: {e}")
                try:
                    print(f"[GATE DEBUG] resp.text full: {resp.text}")
                except Exception:
                    pass
            raise

        # Gate.io may return a list of account entries (one per currency),
        # e.g. [{"currency":"USDT","total":"100.0","available":"50.0",...}, ...]
        # Handle both list and dict responses robustly.
        def _safe_float(value):
            try:
                return float(value or 0)
            except Exception:
                return 0.0

        if self.debug:
            print(f"[GATE DEBUG] get_account raw data: {data}")

        if isinstance(data, list):
            # prefer USDT entry; fall back to first entry
            entry = None
            for item in data:
                if str(item.get('currency', '')).upper() in ('USDT', 'USD'):
                    entry = item
                    break
            if entry is None and len(data) > 0:
                entry = data[0]

            if entry:
                if self.debug:
                    print(f"[GATE DEBUG] get_account entry fields: {entry.keys()}")
                
                # Fetch cross margin specific fields
                cross_margin_balance = _safe_float(entry.get('cross_margin_balance', 0))
                cross_available = _safe_float(entry.get('cross_available', 0))
                cross_initial_margin = _safe_float(entry.get('cross_initial_margin', 0))
                cross_order_margin = _safe_float(entry.get('cross_order_margin', 0))
                
                available = _safe_float(entry.get('available', entry.get('free', 0)))
                raw_total = _safe_float(entry.get('total', entry.get('equity', entry.get('wallet_balance', 0))))
                unrealised_pnl = _safe_float(entry.get('unrealised_pnl', entry.get('unrealized_pnl', entry.get('cross_unrealised_pnl', 0))))
                
                # Determine total equity
                # In cross margin mode, cross_margin_balance is preferred.
                # If not returned (or 0) but cross margin is active (e.g. cross_available > 0),
                # we calculate the cross-margin total equity.
                if cross_margin_balance <= 0 and (cross_available > 0 or cross_initial_margin > 0 or cross_order_margin > 0):
                    cross_margin_balance = cross_available + cross_initial_margin + cross_order_margin
                
                if cross_margin_balance > 0:
                    total = cross_margin_balance
                else:
                    total = raw_total
                
                # Determine available margin
                final_available = cross_available if cross_available > 0 else available
                
                if self.debug:
                    print(f"[GATE DEBUG] cross_available={cross_available}, available={available}, cross_margin_balance={cross_margin_balance}, raw_total={raw_total}, total={total}, unrealised_pnl={unrealised_pnl}")
                    print(f"[GATE DEBUG] selected total equity: {total}, available: {final_available}")
                
                return {
                    'total': total,
                    'available': final_available * 0.5,
                    'unrealised_pnl': unrealised_pnl
                }
            else:
                if self.debug:
                    print("[GATE DEBUG] get_account: no entry found in list response")
                return {'total': 0.0, 'available': 0.0, 'unrealised_pnl': 0.0}

        # If it's a dict, try to parse fields directly
        if isinstance(data, dict):
            if self.debug:
                print(f"[GATE DEBUG] get_account dict fields: {data.keys()}")
            
            # Fetch cross margin specific fields
            cross_margin_balance = _safe_float(data.get('cross_margin_balance', 0))
            cross_available = _safe_float(data.get('cross_available', 0))
            cross_initial_margin = _safe_float(data.get('cross_initial_margin', 0))
            cross_order_margin = _safe_float(data.get('cross_order_margin', 0))
            
            available = _safe_float(data.get('available', data.get('free', 0)))
            raw_total = _safe_float(data.get('total', data.get('equity', data.get('wallet_balance', 0))))
            unrealised_pnl = _safe_float(data.get('unrealised_pnl', data.get('unrealized_pnl', data.get('cross_unrealised_pnl', 0))))
            
            # Determine total equity
            # In cross margin mode, cross_margin_balance is preferred.
            # If not returned (or 0) but cross margin is active (e.g. cross_available > 0),
            # we calculate the cross-margin total equity.
            if cross_margin_balance <= 0 and (cross_available > 0 or cross_initial_margin > 0 or cross_order_margin > 0):
                cross_margin_balance = cross_available + cross_initial_margin + cross_order_margin
            
            if cross_margin_balance > 0:
                total = cross_margin_balance
            else:
                total = raw_total
            
            # Determine available margin
            final_available = cross_available if cross_available > 0 else available
            
            if self.debug:
                print(f"[GATE DEBUG] cross_available={cross_available}, available={available}, cross_margin_balance={cross_margin_balance}, raw_total={raw_total}, total={total}, unrealised_pnl={unrealised_pnl}")
                print(f"[GATE DEBUG] selected total equity: {total}, available: {final_available}")
            
            return {
                'total': total,
                'available': final_available * 0.5,
                'unrealised_pnl': unrealised_pnl
            }

        # Unknown shape
        if self.debug:
            print(f"[GATE DEBUG] get_account: unknown response shape: {type(data)}")
        return {'total': 0.0, 'available': 0.0, 'unrealised_pnl': 0.0}
    
    def get_ticker(self, contract: str) -> dict:
        """获取最新价格"""
        url = f"{BASE_URL}/futures/usdt/tickers"
        params = {"contract": contract}
        
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        if data:
            return {
                'last': float(data[0]['last']),
                'mark_price': float(data[0]['mark_price'])
            }
        return {'last': 0, 'mark_price': 0}
    
    def get_position_closes(self, contract: str, limit: int = 10) -> list:
        """
        获取平仓记录
        用于判断最近的交易是盈利还是亏损
        """
        url_path = f"/api/v4/futures/usdt/position_close"
        full_url = f"{BASE_URL}/futures/usdt/position_close"
        query_string = f"contract={contract}&limit={limit}"
        
        headers = self._sign("GET", url_path, query_string, "")
        resp = self.session.get(full_url, params={"contract": contract, "limit": limit}, headers=headers)
        
        if resp.status_code != 200:
            return []
        
        data = resp.json()
        
        results = []
        for item in data:
            results.append({
                'time': int(item.get('time', 0)),
                'side': item.get('side', ''),  # long 或 short
                'pnl': float(item.get('pnl', 0)),  # 已实现盈亏
                'pnl_pnl': float(item.get('pnl_pnl', 0)),  # 仓位盈亏
                'pnl_fee': float(item.get('pnl_fee', 0)),  # 手续费
                'text': item.get('text', ''),  # 备注
                'entry_price': float(item.get('long_price', 0) or item.get('short_price', 0)),
            })
        
        return results
    
    def get_my_trades(self, contract: str, limit: int = 20) -> list:
        """
        获取成交记录
        """
        url_path = f"/api/v4/futures/usdt/my_trades"
        full_url = f"{BASE_URL}/futures/usdt/my_trades"
        query_string = f"contract={contract}&limit={limit}"
        
        headers = self._sign("GET", url_path, query_string, "")
        resp = self.session.get(full_url, params={"contract": contract, "limit": limit}, headers=headers)
        
        if resp.status_code != 200:
            return []
        
        data = resp.json()
        
        results = []
        for item in data:
            results.append({
                'id': item.get('id'),
                'time': int(item.get('create_time', 0)),
                'size': int(float(item.get('size', 0))),  # 正=买, 负=卖
                'price': float(item.get('price', 0)),
                'order_id': item.get('order_id'),
                'role': item.get('role', ''),
            })
        
        return results
    
    def create_order(self, contract: str, size: int, price: Optional[float] = None,
                     reduce_only: bool = False, text: str = "") -> dict:
        """
        下单
        
        Args:
            contract: 交易对（如 "ETH_USDT"）
            size: 数量（正=做多, 负=做空）
            price: 价格（None 表示市价）
            reduce_only: 是否仅减仓
            text: 订单备注
        
        Returns:
            API 返回的订单信息
        """
        import json
        
        url_path = "/api/v4/futures/usdt/orders"
        full_url = f"{BASE_URL}/futures/usdt/orders"
        
        # 构建订单体
        cleaned_text = self._clean_text(text) if text else ""
        order = {
            "contract": contract,
            "size": str(size),
            "reduce_only": reduce_only,
        }
        if cleaned_text:
            order["text"] = cleaned_text
        
        if price is not None:
            order["price"] = str(price)
            order["tif"] = "gtc"  # Good-till-cancel
        else:
            order["price"] = "0"
            order["tif"] = "ioc"  # Immediate-or-cancel
        
        body = json.dumps(order)
        headers = self._sign("POST", url_path, "", body)
        
        resp = self.session.post(full_url, data=body, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            import sys
            print(f"[GATE ERROR RESPONSE] POST {full_url} Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
            try:
                err_data = resp.json()
                label = err_data.get("label", "")
                msg = err_data.get("message", "")
                if label or msg:
                    raise Exception(f"{e} (Gate Error: {label}: {msg})") from e
            except Exception:
                pass
            raise e
        
        return resp.json()

    def get_price_orders(self, contract: str, status: str = "open", limit: int = 100) -> list:
        """获取触发单（price orders）列表。"""
        url_path = "/api/v4/futures/usdt/price_orders"
        full_url = f"{BASE_URL}/futures/usdt/price_orders"

        params = {
            "contract": contract,
            "status": status,
            "limit": limit,
        }
        query_parts = [f"{k}={v}" for k, v in params.items()]
        query_string = "&".join(query_parts)

        headers = self._sign("GET", url_path, query_string, "")
        resp = self.session.get(full_url, params=params, headers=headers)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data if isinstance(data, list) else []

    def create_price_stop_order(self, contract: str, position_side: str,
                                stop_price: float, text: str = "") -> dict:
        """
        创建持仓止损触发单（price_orders）。

        Args:
            contract: 交易对，例如 ETH_USDT
            position_side: 持仓方向，"long" 或 "short"
            stop_price: 触发价格
            text: 订单备注
        """
        import json

        if position_side not in ("long", "short"):
            raise ValueError("position_side 必须是 long 或 short")

        # Gate 规则：rule=1 价格 >= 触发价；rule=2 价格 <= 触发价
        # 多仓止损：价格下破触发，使用 rule=2
        # 空仓止损：价格上破触发，使用 rule=1
        rule = 2 if position_side == "long" else 1

        url_path = "/api/v4/futures/usdt/price_orders"
        full_url = f"{BASE_URL}/futures/usdt/price_orders"

        order_text = text or f"stop_loss_{position_side}_{int(time.time())}"
        cleaned_text = self._clean_text(order_text)
        body_obj = {
            "trigger": {
                "strategy_type": 0,
                "price_type": 0,
                "price": str(stop_price),
                "rule": rule,
                "expiration": 0,
            },
            "initial": {
                "contract": contract,
                "size": "0",
                "price": "0",
                "tif": "ioc",
                "text": cleaned_text,
                "reduce_only": True,
                "auto_size": "close",
            },
        }

        body = json.dumps(body_obj)
        headers = self._sign("POST", url_path, "", body)
        resp = self.session.post(full_url, data=body, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            import sys
            print(f"[GATE ERROR RESPONSE] POST {full_url} Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
            try:
                err_data = resp.json()
                label = err_data.get("label", "")
                msg = err_data.get("message", "")
                if label or msg:
                    raise Exception(f"{e} (Gate Error: {label}: {msg})") from e
            except Exception:
                pass
            raise e
        return resp.json()

    def cancel_price_order(self, order_id: str) -> dict:
        """按 ID 取消单个触发单。"""
        url_path = f"/api/v4/futures/usdt/price_orders/{order_id}"
        full_url = f"{BASE_URL}/futures/usdt/price_orders/{order_id}"

        headers = self._sign("DELETE", url_path, "", "")
        resp = self.session.delete(full_url, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            import sys
            print(f"[GATE ERROR RESPONSE] DELETE {full_url} Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
            raise e
        return resp.json()

    def update_price_order(self, order_id: str, new_trigger_price: float, contract: str = "ETH_USDT") -> dict:
        """
        更新触发单的触发价格。
        
        由于Gate.io REST API的PUT端点返回"Invalid param:order_id"错误，
        暂无法直接修改现有订单。采用cancel+create方案实现功能等价性：
        1. 取消现有订单（order_id会改变）
        2. 创建新订单，保留所有原始参数（除trigger_price外）
        
        注：WebSocket或Gate.io UI可能支持真正的in-place修改，但REST API限制。
        """
        try:
            # 第1步：查询现有订单获取参数
            existing = self.get_price_orders(contract=contract, status="open", limit=100)
            target_order = None
            for o in existing:
                if str(o.get("id")) == str(order_id):
                    target_order = o
                    break
            
            if not target_order:
                return {"success": False, "message": f"Order {order_id} not found"}
            
            # 第2步：取消现有订单
            self.cancel_price_order(order_id)
            
            # 第3步：提取原订单参数
            contract = target_order.get("initial", {}).get("contract", "ETH_USDT")
            rule = target_order.get("trigger", {}).get("rule", 1)
            original_text = target_order.get("initial", {}).get("text", "")
            cleaned_text = self._clean_text(original_text)
            
            # 第4步：创建新订单（保留所有原始参数）
            new_body = {
                "trigger": {
                    "strategy_type": 0,
                    "price_type": 0,
                    "price": str(new_trigger_price),
                    "rule": rule,
                    "expiration": 0,
                },
                "initial": {
                    "contract": contract,
                    "size": "0",
                    "price": "0",
                    "tif": "ioc",
                    "text": cleaned_text,
                    "reduce_only": True,
                    "auto_size": "close",
                },
            }
            
            url_path = "/api/v4/futures/usdt/price_orders"
            full_url = f"{BASE_URL}/futures/usdt/price_orders"
            body = json.dumps(new_body)
            headers = self._sign("POST", url_path, "", body)
            resp = self.session.post(full_url, data=body, headers=headers)
            try:
                resp.raise_for_status()
            except requests.exceptions.HTTPError as e:
                import sys
                print(f"[GATE ERROR RESPONSE] POST {full_url} Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
                try:
                    err_data = resp.json()
                    label = err_data.get("label", "")
                    msg = err_data.get("message", "")
                    if label or msg:
                        raise Exception(f"{e} (Gate Error: {label}: {msg})") from e
                except Exception:
                    pass
                raise e
            
            new_order = resp.json()
            return {
                "success": True,
                "message": f"Order updated (API constraint: ID changed from {order_id})",
                "old_id": order_id,
                "new_id": new_order.get("id")
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    def cancel_price_orders(self, contract: str) -> list:
        """取消某个合约的所有 open 触发单。"""
        cancelled = []
        for order in self.get_price_orders(contract=contract, status="open", limit=100):
            order_id = order.get("id") or order.get("id_string")
            if not order_id:
                continue
            try:
                result = self.cancel_price_order(str(order_id))
                cancelled.append(result)
            except Exception:
                # 单笔取消失败不影响其他单
                continue
        return cancelled
    
    def cancel_orders(self, contract: str, side: Optional[str] = None, text: str = "") -> list:
        """
        取消订单
        
        Args:
            contract: 交易对
            side: "buy" 或 "sell" 或 None（取消该交易对的所有订单）
            text: 订单备注（取消指定备注的订单）
        
        Returns:
            取消的订单列表
        """
        url_path = "/api/v4/futures/usdt/orders"
        full_url = f"{BASE_URL}/futures/usdt/orders"
        
        params = {"contract": contract}
        if side:
            params["side"] = side
        if text:
            params["text"] = self._clean_text(text)
        
        # 构建查询字符串
        query_parts = [f"{k}={v}" for k, v in params.items()]
        query_string = "&".join(query_parts)
        
        headers = self._sign("DELETE", url_path, query_string, "")
        resp = self.session.delete(full_url, params=params, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            import sys
            print(f"[GATE ERROR RESPONSE] DELETE {full_url} Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
            raise e
        
        return resp.json()
    
    def get_orders(self, contract: str, status: str = "open", limit: int = 100) -> list:
        """
        获取订单列表
        
        Args:
            contract: 交易对
            status: "open" / "finished"
            limit: 限制数量
        
        Returns:
            订单列表
        """
        url_path = "/api/v4/futures/usdt/orders"
        full_url = f"{BASE_URL}/futures/usdt/orders"
        
        params = {
            "contract": contract,
            "status": status,
            "limit": limit
        }
        
        query_parts = [f"{k}={v}" for k, v in params.items()]
        query_string = "&".join(query_parts)
        
        headers = self._sign("GET", url_path, query_string, "")
        resp = self.session.get(full_url, params=params, headers=headers)
        
        if resp.status_code != 200:
            return []
        
        return resp.json()
    
    def update_position_margin(self, contract: str, change: float) -> dict:
        """
        调整保证金（用于杠杆调整）
        
        Args:
            contract: 交易对
            change: 增加的保证金额度（USDT），负数表示减少
        
        Returns:
            API 返回结果
        """
        import json
        
        url_path = "/api/v4/futures/usdt/positions/ETH_USDT/margin"
        full_url = f"{BASE_URL}/futures/usdt/positions/{contract}/margin"
        
        body = json.dumps({"change": str(change)})
        headers = self._sign("POST", url_path, "", body)
        
        resp = self.session.post(full_url, data=body, headers=headers)
        resp.raise_for_status()
        
        return resp.json()
