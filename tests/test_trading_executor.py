import os
import pytest

from gate_client import GateClient
import trading_executor as te
import config


class DummyClient(GateClient):
    def __init__(self):
        # do not call parent init to avoid needing keys
        self.session = type('S', (), {'post': lambda *a, **k: None})()


def test_dry_run_open_close(tmp_path, monkeypatch):
    # ensure auto trading disabled
    monkeypatch.setenv('ENABLE_AUTO_TRADING', 'false')
    # reload config module to pick env
    import importlib
    importlib.reload(config)

    client = DummyClient()
    executor = te.TradingExecutor(client)

    open_res = executor.open_position('ETH_USDT', 'long', 10)
    assert open_res['executed'] is False
    assert open_res['reason'] == 'dry_run'

    adjust_res = executor.adjust_stop('ETH_USDT', 'long', 10, 2400.0)
    assert adjust_res['executed'] is False

    close_res = executor.close_position('ETH_USDT', 'long', 10)
    assert close_res['executed'] is False


def test_enabled_run_simulated(monkeypatch):
    # enable auto trading
    monkeypatch.setenv('ENABLE_AUTO_TRADING', 'true')
    import importlib
    importlib.reload(config)

    client = DummyClient()
    executor = te.TradingExecutor(client)

    # Because real calls are commented, expect executed True but simulated result
    res = executor.open_position('ETH_USDT', 'short', 5)
    assert res['executed'] is True
    assert res['result']['action'] == 'open'

    res2 = executor.adjust_stop('ETH_USDT', 'short', 5, 2350.0)
    assert res2['executed'] is True
    assert res2['result']['action'] == 'adjust_stop'

    res3 = executor.close_position('ETH_USDT', 'short', 5)
    assert res3['executed'] is True
    assert res3['result']['action'] == 'close'
"""
交易执行器单元测试
"""

import pytest
from trading_executor import TradeExecutor


class MockClient:
    """模拟 Gate.io 客户端"""
    pass


class TestTradeExecutor:
    """TradeExecutor 单元测试"""

    @pytest.fixture
    def executor_dry_run(self):
        """创建干运行模式的执行器"""
        return TradeExecutor(MockClient(), contract="ETH_USDT", dry_run=True)

    def test_open_position_long_success(self, executor_dry_run):
        """测试成功开多仓"""
        result = executor_dry_run.open_position(
            direction="long",
            entry_price=2813.0,
            stop_loss=2800.0,
            qty=27
        )
        assert result["success"] == True
        assert "开多" in result["message"]
        assert result["order_info"]["qty"] == 27
        assert result["order_info"]["direction"] == "long"

    def test_open_position_short_success(self, executor_dry_run):
        """测试成功开空仓"""
        result = executor_dry_run.open_position(
            direction="short",
            entry_price=2813.0,
            stop_loss=2826.0,
            qty=27
        )
        assert result["success"] == True
        assert "开空" in result["message"]
        assert result["order_info"]["qty"] == 27
        assert result["order_info"]["direction"] == "short"

    def test_open_position_invalid_qty(self, executor_dry_run):
        """测试张数 <= 0 的错误"""
        result = executor_dry_run.open_position(
            direction="long",
            entry_price=2813.0,
            stop_loss=2800.0,
            qty=0
        )
        assert result["success"] == False
        assert "张数必须 > 0" in result["message"]

    def test_adjust_stop_loss_long_up_success(self, executor_dry_run):
        """测试多仓止损上移"""
        result = executor_dry_run.adjust_stop_loss(
            direction="long",
            current_stop=2800.0,
            new_stop=2810.0
        )
        assert result["success"] == True
        assert "调整" in result["message"]
        assert "2800.0" in result["message"]
        assert "2810.0" in result["message"]

    def test_adjust_stop_loss_long_down_fail(self, executor_dry_run):
        """测试多仓止损下移（应失败）"""
        result = executor_dry_run.adjust_stop_loss(
            direction="long",
            current_stop=2810.0,
            new_stop=2800.0
        )
        assert result["success"] == False
        assert "只能上移" in result["message"]

    def test_adjust_stop_loss_short_down_success(self, executor_dry_run):
        """测试空仓止损下移"""
        result = executor_dry_run.adjust_stop_loss(
            direction="short",
            current_stop=2826.0,
            new_stop=2816.0
        )
        assert result["success"] == True
        assert "调整" in result["message"]
        assert "2826.0" in result["message"]
        assert "2816.0" in result["message"]

    def test_adjust_stop_loss_short_up_fail(self, executor_dry_run):
        """测试空仓止损上移（应失败）"""
        result = executor_dry_run.adjust_stop_loss(
            direction="short",
            current_stop=2816.0,
            new_stop=2826.0
        )
        assert result["success"] == False
        assert "只能下移" in result["message"]

    def test_close_position_long_with_price(self, executor_dry_run):
        """测试平多仓（指定价格）"""
        result = executor_dry_run.close_position(
            direction="long",
            qty=27,
            exit_price=2820.0
        )
        assert result["success"] == True
        assert "平多" in result["message"]
        assert "2820.0" in result["message"]
        assert result["order_info"]["qty"] == 27

    def test_close_position_short_market(self, executor_dry_run):
        """测试平空仓（市价）"""
        result = executor_dry_run.close_position(
            direction="short",
            qty=27,
            exit_price=None
        )
        assert result["success"] == True
        assert "平空" in result["message"]
        assert "市价" in result["message"]

    def test_close_position_invalid_qty(self, executor_dry_run):
        """测试平仓张数 <= 0 的错误"""
        result = executor_dry_run.close_position(
            direction="long",
            qty=-1,
            exit_price=2820.0
        )
        assert result["success"] == False
        assert "张数必须 > 0" in result["message"]

    def test_order_id_generation(self, executor_dry_run):
        """验证模拟订单 ID 生成"""
        result1 = executor_dry_run.open_position("long", 2813.0, 2800.0, 27)
        result2 = executor_dry_run.open_position("short", 2813.0, 2826.0, 27)
        
        # 订单 ID 应该不同
        assert result1["order_id"] != result2["order_id"]
        assert result1["order_id"].startswith("sim_long")
        assert result2["order_id"].startswith("sim_short")


class TestTradeExecutorIntegration:
    """集成测试场景"""

    @pytest.fixture
    def executor(self):
        return TradeExecutor(MockClient(), contract="ETH_USDT", dry_run=True)

    def test_full_trading_cycle(self, executor):
        """完整交易周期：开仓 → 调止损 → 平仓"""
        # 1. 开仓
        open_result = executor.open_position(
            direction="long",
            entry_price=2813.0,
            stop_loss=2800.0,
            qty=27
        )
        assert open_result["success"] == True
        
        # 2. 调整止损（上移）
        adjust_result = executor.adjust_stop_loss(
            direction="long",
            current_stop=2800.0,
            new_stop=2810.0
        )
        assert adjust_result["success"] == True
        
        # 3. 再次调整止损（上移）
        adjust_result2 = executor.adjust_stop_loss(
            direction="long",
            current_stop=2810.0,
            new_stop=2815.0
        )
        assert adjust_result2["success"] == True
        
        # 4. 平仓
        close_result = executor.close_position(
            direction="long",
            qty=27,
            exit_price=2825.0
        )
        assert close_result["success"] == True

    def test_short_trading_cycle(self, executor):
        """空仓完整交易周期"""
        # 1. 开空仓
        open_result = executor.open_position(
            direction="short",
            entry_price=2813.0,
            stop_loss=2826.0,
            qty=27
        )
        assert open_result["success"] == True
        
        # 2. 调整止损（下移）
        adjust_result = executor.adjust_stop_loss(
            direction="short",
            current_stop=2826.0,
            new_stop=2820.0
        )
        assert adjust_result["success"] == True
        
        # 3. 平仓
        close_result = executor.close_position(
            direction="short",
            qty=27,
            exit_price=2800.0
        )
        assert close_result["success"] == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
