"""
Gate.io API 客户端
获取 K线数据和持仓信息
"""

import time
import hashlib
import hmac
import requests
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
        self.debug = bool(debug or os.getenv('GATE_DEBUG'))
    
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
            "Content-Type": "application/json"
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
        if data.get('size', 0) == 0:
            return None
        
        return {
            'size': int(data['size']),  # 正=多, 负=空
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
                
                # Gate.io返回的字段优先级:
                # 1. cross_available (全仓模式的可用余额) - 最准确
                # 2. available (隔离仓的可用余额)
                # 3. total (账户总资金)
                # 4. equity (权益)
                cross_available = _safe_float(entry.get('cross_available', 0))
                available = _safe_float(entry.get('available', entry.get('free', 0)))
                total = _safe_float(entry.get('total', entry.get('equity', entry.get('wallet_balance', 0))))
                unrealised_pnl = _safe_float(entry.get('unrealised_pnl', entry.get('unrealized_pnl', entry.get('cross_unrealised_pnl', 0))))
                
                # 选择最合适的本金字段
                if cross_available > 0:
                    final_total = cross_available  # 全仓模式，用cross_available
                elif available > 0:
                    final_total = available  # 隔离仓模式或cross_available不存在
                else:
                    final_total = total  # 其他情况
                
                if self.debug:
                    print(f"[GATE DEBUG] cross_available={cross_available}, available={available}, total={total}, unrealised_pnl={unrealised_pnl}")
                    print(f"[GATE DEBUG] selected total field: {final_total}")
                
                return {
                    'total': final_total,
                    'available': available,
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
            
            # Gate.io返回的字段优先级:
            cross_available = _safe_float(data.get('cross_available', 0))
            available = _safe_float(data.get('available', data.get('free', 0)))
            total = _safe_float(data.get('total', data.get('equity', data.get('wallet_balance', 0))))
            unrealised_pnl = _safe_float(data.get('unrealised_pnl', data.get('unrealized_pnl', data.get('cross_unrealised_pnl', 0))))
            
            # 选择最合适的本金字段
            if cross_available > 0:
                final_total = cross_available
            elif available > 0:
                final_total = available
            else:
                final_total = total
            
            if self.debug:
                print(f"[GATE DEBUG] cross_available={cross_available}, available={available}, total={total}, unrealised_pnl={unrealised_pnl}")
                print(f"[GATE DEBUG] selected total field: {final_total}")
            
            return {
                'total': final_total,
                'available': available,
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
                'size': int(item.get('size', 0)),  # 正=买, 负=卖
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
        order = {
            "contract": contract,
            "size": size,
            "reduce_only": reduce_only,
            "text": text
        }
        
        if price is not None:
            order["price"] = str(price)
            order["time_in_force"] = "gtc"  # Good-till-cancel
        else:
            order["price"] = "market"
            order["time_in_force"] = "ioc"  # Immediate-or-cancel
        
        body = json.dumps(order)
        headers = self._sign("POST", url_path, "", body)
        
        resp = self.session.post(full_url, data=body, headers=headers)
        resp.raise_for_status()
        
        return resp.json()
    
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
            params["text"] = text
        
        # 构建查询字符串
        query_parts = [f"{k}={v}" for k, v in params.items()]
        query_string = "&".join(query_parts)
        
        headers = self._sign("DELETE", url_path, query_string, "")
        resp = self.session.delete(full_url, params=params, headers=headers)
        resp.raise_for_status()
        
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
