"""模拟 GateClient.get_account() 不同响应格式的脚本
运行方式：python3 tests/simulate_gate_client.py
"""
import json
from gate_client import GateClient


class FakeResp:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise Exception(f"HTTP {self.status_code}")


class DummySession:
    def __init__(self, resp):
        self._resp = resp

    def get(self, *args, **kwargs):
        return self._resp


def run_case(name, data):
    print(f"--- {name} ---")
    resp = FakeResp(200, data)
    client = GateClient(api_key="k", api_secret="s")
    client.session = DummySession(resp)
    try:
        account = client.get_account()
        print(json.dumps(account, indent=2, ensure_ascii=False))
    except Exception as e:
        print("Error:", e)
    print()


if __name__ == '__main__':
    # 1. 列表格式，包含 USDT
    data_list = [
        {"currency": "BTC", "total": "0.1", "available": "0.05"},
        {"currency": "USDT", "total": "100.5", "available": "50.25", "unrealised_pnl": "-1.2"}
    ]

    # 2. 列表格式，但没有 USDT -> fallback to first entry
    data_list_no_usdt = [
        {"currency": "USD", "total": "200.0", "available": "150.0"}
    ]

    # 3. dict 格式
    data_dict = {"total": "300.0", "available": "250.0", "unrealised_pnl": "2.5"}

    # 4. 空列表
    data_empty = []

    run_case("List with USDT", data_list)
    run_case("List without USDT (fallback)", data_list_no_usdt)
    run_case("Dict response", data_dict)
    run_case("Empty list", data_empty)
