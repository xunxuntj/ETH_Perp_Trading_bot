import os
import time
import pytest
from unittest.mock import MagicMock
from trading_executor import TradeExecutor
from gate_client import GateClient

class MockClient:
    """模拟 Gate.io 客户端"""
    def __init__(self):
        self.create_order = MagicMock(return_value={"id": "mock_order_id"})
        self.create_price_stop_order = MagicMock(return_value={"id": "mock_stop_id"})
        self.cancel_price_orders = MagicMock(return_value=None)
        self.cancel_orders = MagicMock(return_value=None)
        self.get_price_orders = MagicMock(return_value=[{"id": "mock_existing_stop_id"}])
        self.update_price_order = MagicMock(return_value={"id": "mock_existing_stop_id"})
        self.get_position_detail = MagicMock(return_value={"pos_margin_mode": "cross", "leverage": 0, "cross_leverage_limit": 0})
        self.update_position_leverage = MagicMock(return_value={"success": True})

class TestTradeExecutor:
    """TradeExecutor 单元测试"""

    @pytest.fixture
    def mock_client(self):
        return MockClient()

    @pytest.fixture
    def executor_dry_run(self, mock_client):
        """创建强制干运行模式的执行器"""
        executor = TradeExecutor(mock_client, contract="ETH_USDT")
        executor.dry_run = True  # force dry run for testing
        return executor

    @pytest.fixture
    def executor_live_run(self, mock_client):
        """创建强制实盘模拟模式的执行器"""
        executor = TradeExecutor(mock_client, contract="ETH_USDT")
        executor.dry_run = False  # force live run for testing
        return executor

    def test_open_long_success(self, executor_dry_run):
        """测试成功开多仓"""
        result = executor_dry_run.open_long(
            entry_price=2813.0,
            stop_loss=2800.0,
            qty=27
        )
        assert result["success"] is True
        assert "开多" in result["message"]
        assert result["details"]["qty"] == 27
        assert result["details"]["stop_loss"] == 2800.0

    def test_open_short_success(self, executor_dry_run):
        """测试成功开空仓"""
        result = executor_dry_run.open_short(
            entry_price=2813.0,
            stop_loss=2826.0,
            qty=27
        )
        assert result["success"] is True
        assert "开空" in result["message"]
        assert result["details"]["qty"] == 27
        assert result["details"]["stop_loss"] == 2826.0

    def test_open_long_invalid_qty(self, executor_dry_run):
        """测试张数 <= 0 的错误"""
        result = executor_dry_run.open_long(
            entry_price=2813.0,
            stop_loss=2800.0,
            qty=0
        )
        assert result["success"] is False
        assert "张数必须 > 0" in result["message"]

    def test_open_long_invalid_stop_loss(self, executor_dry_run):
        """测试多仓止损价 >= 入场价的错误"""
        result = executor_dry_run.open_long(
            entry_price=2800.0,
            stop_loss=2810.0,
            qty=10
        )
        assert result["success"] is False
        assert "止损价" in result["message"]

    def test_open_short_invalid_stop_loss(self, executor_dry_run):
        """测试空仓止损价 <= 入场价的错误"""
        result = executor_dry_run.open_short(
            entry_price=2800.0,
            stop_loss=2790.0,
            qty=10
        )
        assert result["success"] is False
        assert "止损价" in result["message"]

    def test_sync_leverage_cross_mode(self, executor_live_run, mock_client):
        """测试全仓模式下的杠杆同步"""
        mock_client.get_position_detail = MagicMock(return_value={
            "pos_margin_mode": "cross",
            "leverage": 0,
            "cross_leverage_limit": 100
        })
        mock_client.update_position_leverage = MagicMock(return_value={"status": "success"})
        
        result = executor_live_run.sync_leverage()
        assert result is True
        mock_client.update_position_leverage.assert_called_with(
            contract="ETH_USDT",
            leverage="0",
            cross_leverage_limit="10"
        )

    def test_sync_leverage_isolated_mode(self, executor_live_run, mock_client):
        """测试逐仓模式下的杠杆同步"""
        mock_client.get_position_detail = MagicMock(return_value={
            "pos_margin_mode": "isolated",
            "leverage": 100,
            "cross_leverage_limit": 0
        })
        mock_client.update_position_leverage = MagicMock(return_value={"status": "success"})
        
        result = executor_live_run.sync_leverage()
        assert result is True
        mock_client.update_position_leverage.assert_called_with(
            contract="ETH_USDT",
            leverage="10",
            cross_leverage_limit=""
        )

    def test_adjust_stop_loss_long_up_success(self, executor_dry_run):
        """测试多仓止损上移"""
        result = executor_dry_run.adjust_stop_loss(
            direction="long",
            new_stop=2810.0,
            qty=27,
            old_stop=2800.0
        )
        assert result["success"] is True
        assert "已调整" in result["message"]
        assert result["details"]["new_stop"] == 2810.0

    def test_adjust_stop_loss_long_down_fail(self, executor_dry_run):
        """测试多仓止损下移（应失败）"""
        result = executor_dry_run.adjust_stop_loss(
            direction="long",
            new_stop=2800.0,
            qty=27,
            old_stop=2810.0
        )
        assert result["success"] is False
        assert "只能上移" in result["message"]

    def test_adjust_stop_loss_short_down_success(self, executor_dry_run):
        """测试空仓止损下移"""
        result = executor_dry_run.adjust_stop_loss(
            direction="short",
            new_stop=2816.0,
            qty=27,
            old_stop=2826.0
        )
        assert result["success"] is True
        assert "已调整" in result["message"]
        assert result["details"]["new_stop"] == 2816.0

    def test_adjust_stop_loss_short_up_fail(self, executor_dry_run):
        """测试空仓止损上移（应失败）"""
        result = executor_dry_run.adjust_stop_loss(
            direction="short",
            new_stop=2826.0,
            qty=27,
            old_stop=2816.0
        )
        assert result["success"] is False
        assert "只能下移" in result["message"]

    def test_close_position_long_success(self, executor_dry_run):
        """测试平多仓"""
        result = executor_dry_run.close_position(
            direction="long",
            qty=27,
            pnl=10.5
        )
        assert result["success"] is True
        assert "平多" in result["message"]
        assert result["details"]["qty"] == 27
        assert result["details"]["pnl"] == 10.5

    def test_close_position_invalid_qty(self, executor_dry_run):
        """测试平仓张数 <= 0 的错误"""
        result = executor_dry_run.close_position(
            direction="long",
            qty=0
        )
        assert result["success"] is False
        assert "张数必须 > 0" in result["message"]

    def test_order_id_generation(self, executor_dry_run):
        """验证模拟订单 ID 生成"""
        result1 = executor_dry_run.open_long(2813.0, 2800.0, 27)
        result2 = executor_dry_run.open_short(2813.0, 2826.0, 27)
        
        # 订单 ID 应该不同
        assert result1["order_id"] != result2["order_id"]
        assert result1["order_id"].startswith("sim_long")
        assert result2["order_id"].startswith("sim_short")

    def test_live_run_methods_called(self, executor_live_run, mock_client):
        """测试实盘模式下 client 方法被正确调用"""
        # Test open long
        res_long = executor_live_run.open_long(2813.0, 2800.0, 27)
        assert res_long["success"] is True
        mock_client.create_order.assert_called_with(
            contract="ETH_USDT",
            size=27,
            price=None,
            reduce_only=False,
            text=mock_client.create_order.call_args[1]["text"]
        )

        # Test adjust stop loss (update existing)
        res_adjust = executor_live_run.adjust_stop_loss(
            direction="long",
            new_stop=2810.0,
            qty=27,
            old_stop=2800.0
        )
        assert res_adjust["success"] is True
        mock_client.update_price_order.assert_called_with("mock_existing_stop_id", 2810.0, "ETH_USDT")

        # Test close position
        res_close = executor_live_run.close_position(direction="long", qty=27, pnl=5.0)
        assert res_close["success"] is True
        mock_client.create_order.assert_called_with(
            contract="ETH_USDT",
            size=-27,
            price=None,
            reduce_only=True,
            text=mock_client.create_order.call_args[1]["text"]
        )


class TestTradeExecutorIntegration:
    """集成测试场景"""

    @pytest.fixture
    def executor(self):
        return TradeExecutor(MockClient(), contract="ETH_USDT")
        
    def test_full_trading_cycle(self, executor):
        """完整交易周期：开仓 → 调止损 → 平仓"""
        executor.dry_run = True

        # 1. 开仓
        open_result = executor.open_long(
            entry_price=2813.0,
            stop_loss=2800.0,
            qty=27
        )
        assert open_result["success"] is True
        
        # 2. 调整止损（上移）
        adjust_result = executor.adjust_stop_loss(
            direction="long",
            new_stop=2810.0,
            qty=27,
            old_stop=2800.0
        )
        assert adjust_result["success"] is True
        
        # 3. 再次调整止损（上移）
        adjust_result2 = executor.adjust_stop_loss(
            direction="long",
            new_stop=2815.0,
            qty=27,
            old_stop=2810.0
        )
        assert adjust_result2["success"] is True
        
        # 4. 平仓
        close_result = executor.close_position(
            direction="long",
            qty=27,
            pnl=12.0
        )
        assert close_result["success"] is True

    def test_short_trading_cycle(self, executor):
        """空仓完整交易周期"""
        executor.dry_run = True

        # 1. 开空仓
        open_result = executor.open_short(
            entry_price=2813.0,
            stop_loss=2826.0,
            qty=27
        )
        assert open_result["success"] is True
        
        # 2. 调整止损（下移）
        adjust_result = executor.adjust_stop_loss(
            direction="short",
            new_stop=2820.0,
            qty=27,
            old_stop=2826.0
        )
        assert adjust_result["success"] is True
        
        # 3. 平仓
        close_result = executor.close_position(
            direction="short",
            qty=27,
            pnl=15.0
        )
        assert close_result["success"] is True
