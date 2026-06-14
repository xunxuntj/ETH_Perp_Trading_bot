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
            qty=27,
            tp_price=2900.0
        )
        assert result["success"] is True
        assert "开多" in result["message"]
        assert "限价止盈" in result["message"]
        assert result["details"]["qty"] == 27
        assert result["details"]["stop_loss"] == 2800.0
        assert result["details"]["tp_price"] == 2900.0
        assert result["details"]["tp_order_id"] is not None

    def test_open_short_success(self, executor_dry_run):
        """测试成功开空仓"""
        result = executor_dry_run.open_short(
            entry_price=2813.0,
            stop_loss=2826.0,
            qty=27,
            tp_price=2750.0
        )
        assert result["success"] is True
        assert "开空" in result["message"]
        assert "限价止盈" in result["message"]
        assert result["details"]["qty"] == 27
        assert result["details"]["stop_loss"] == 2826.0
        assert result["details"]["tp_price"] == 2750.0
        assert result["details"]["tp_order_id"] is not None

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

    def test_sync_leverage_uninitialized_force_cross_success(self, executor_live_run, mock_client):
        """测试未初始化合约时直接强制更新全仓杠杆成功"""
        # get_position_detail 模拟抛出异常
        mock_client.get_position_detail = MagicMock(side_effect=Exception("Position not found"))
        mock_client.update_position_leverage = MagicMock(return_value={"status": "success"})
        
        result = executor_live_run.sync_leverage()
        assert result is True
        # 验证第一次尝试了全仓杠杆设置
        mock_client.update_position_leverage.assert_called_once_with(
            contract="ETH_USDT",
            leverage="0",
            cross_leverage_limit="10"
        )

    def test_sync_leverage_uninitialized_force_isolated_success(self, executor_live_run, mock_client):
        """测试未初始化合约时强制全仓设置失败，但逐仓设置成功"""
        mock_client.get_position_detail = MagicMock(side_effect=Exception("Position not found"))
        
        # 第一次调用全仓抛异常，第二次调用逐仓成功
        mock_client.update_position_leverage = MagicMock(side_effect=[
            Exception("Cross mode not supported"),
            {"status": "success"}
        ])
        
        result = executor_live_run.sync_leverage()
        assert result is True
        # 验证调用了两次，分别以不同参数
        assert mock_client.update_position_leverage.call_count == 2
        mock_client.update_position_leverage.assert_any_call(
            contract="ETH_USDT",
            leverage="0",
            cross_leverage_limit="10"
        )
        mock_client.update_position_leverage.assert_any_call(
            contract="ETH_USDT",
            leverage="10",
            cross_leverage_limit=""
        )

    def test_sync_leverage_uninitialized_force_fail(self, executor_live_run, mock_client):
        """测试未初始化合约时强制全仓和逐仓更新全部失败"""
        mock_client.get_position_detail = MagicMock(side_effect=Exception("Position not found"))
        mock_client.update_position_leverage = MagicMock(side_effect=Exception("API Error"))
        
        result = executor_live_run.sync_leverage()
        assert result is False
        assert mock_client.update_position_leverage.call_count == 2

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
        # Test open long with limit TP
        mock_client.create_order.reset_mock()
        res_long = executor_live_run.open_long(2813.0, 2800.0, 27, 2900.0)
        assert res_long["success"] is True
        # Verify both entry buy order and limit TP sell order are created
        mock_client.create_order.assert_any_call(
            contract="ETH_USDT",
            size=27,
            price=None,
            reduce_only=False,
            text=mock_client.create_order.call_args_list[0][1]["text"]
        )
        mock_client.create_order.assert_any_call(
            contract="ETH_USDT",
            size=-27,
            price=2900.0,
            reduce_only=True,
            text=mock_client.create_order.call_args_list[1][1]["text"]
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

        # Test open short with limit TP
        mock_client.create_order.reset_mock()
        res_short = executor_live_run.open_short(2813.0, 2826.0, 27, 2750.0)
        assert res_short["success"] is True
        # Verify both entry short order and limit TP buy order are created
        mock_client.create_order.assert_any_call(
            contract="ETH_USDT",
            size=-27,
            price=None,
            reduce_only=False,
            text=mock_client.create_order.call_args_list[0][1]["text"]
        )
        mock_client.create_order.assert_any_call(
            contract="ETH_USDT",
            size=27,
            price=2750.0,
            reduce_only=True,
            text=mock_client.create_order.call_args_list[1][1]["text"]
        )

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

    def test_open_long_sequence(self, executor_live_run, mock_client):
        """测试开仓时止损设置采用先创后撤的顺序"""
        mock_client.create_price_stop_order.reset_mock()
        mock_client.cancel_price_orders.reset_mock()
        
        call_sequence = []
        mock_client.create_price_stop_order.side_effect = lambda *args, **kwargs: (call_sequence.append("create"), {"id": "new_stop_id"})[1]
        mock_client.cancel_price_orders.side_effect = lambda *args, **kwargs: call_sequence.append("cancel")
        
        result = executor_live_run.open_long(
            entry_price=2813.0,
            stop_loss=2800.0,
            qty=27
        )
        assert result["success"] is True
        assert call_sequence == ["create", "cancel"]

    def test_adjust_stop_loss_sequence(self):
        """测试调整止损采用先创后撤的顺序"""
        # 直接测试 GateClient 中的 update_price_order 方法实现先创后撤
        client = GateClient(api_key="mock", api_secret="mock")
        client.get_price_orders = MagicMock(return_value=[{
            "id": "old_order_id",
            "initial": {
                "contract": "ETH_USDT",
                "text": "stop_loss_long_123",
                "reduce_only": True
            },
            "trigger": {
                "rule": 2
            }
        }])
        
        call_sequence = []
        client.session.post = MagicMock(side_effect=lambda *args, **kwargs: (
            call_sequence.append("create"), 
            MagicMock(status_code=200, json=lambda: {"id": "new_order_id"})
        )[1])
        client.cancel_price_order = MagicMock(side_effect=lambda *args, **kwargs: call_sequence.append("cancel"))
        
        res = client.update_price_order("old_order_id", 2800.0, "ETH_USDT")
        assert res["success"] is True
        assert call_sequence == ["create", "cancel"]


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
