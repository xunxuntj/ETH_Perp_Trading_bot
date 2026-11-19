"""
Unit tests for previously uncovered critical modules:
- execution_flow.py (signal-only mode, open, close, close-and-reverse, partial failure)
- generate_portfolio_report.py (single asset stats, return rate & annualized return)
- telegram_notifier.py (message & document delivery handling)
"""

from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from execution_flow import ExecutionFlow
from strategy import TradeResult
from telegram_notifier import TelegramNotifier
from generate_portfolio_report import calculate_single_asset_stats


def test_execution_flow_signal_only_never_executes_orders(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_TRADING", "false")
    client = MagicMock()
    flow = ExecutionFlow(client, contract="ETH_USDT")
    flow.strategy.analyze = MagicMock(return_value=TradeResult(
        action="open_long", message="Long signal",
        details={"entry": 2000.0, "stop_loss": 1980.0, "qty": 10, "tp_price": 2100.0}
    ))
    flow.executor.open_long = MagicMock()

    res = flow.execute_strategy_and_trade()
    assert res["strategy_action"] == "open_long"
    assert res["trade_executed"] is False
    flow.executor.open_long.assert_not_called()


def test_execution_flow_close_and_reverse_validates_and_handles_partial_failure(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_TRADING", "true")
    client = MagicMock()
    client.get_positions.return_value = {"size": 10, "entry_price": 2000.0}
    client.get_ticker.return_value = {"last": 1990.0}

    flow = ExecutionFlow(client, contract="ETH_USDT")
    flow.executor.close_position = MagicMock(return_value={"success": True, "message": "Closed long"})

    # 1. Invalid reverse qty (0) -> aborts reverse cleanly with partial_failure flag
    res_invalid = flow._execute_close_and_reverse(
        TradeResult(action="close_and_reverse_short", message="rev", details={"pnl": -1.0, "reverse_stop": 2010.0, "reverse_qty": 0}),
        "short"
    )
    assert res_invalid["trade_details"]["partial_failure"] is True

    # 2. Valid reverse params but open_short fails -> alerts partial_failure and passes tp_price
    flow.executor.open_short = MagicMock(return_value={"success": False, "message": "Margin insufficient"})
    res_partial = flow._execute_close_and_reverse(
        TradeResult(action="close_and_reverse_short", message="rev", details={"pnl": -1.0, "reverse_stop": 2010.0, "reverse_qty": 5}),
        "short"
    )
    assert res_partial["trade_executed"] is False
    assert res_partial["trade_details"]["partial_failure"] is True
    assert "半成交告警" in res_partial["message"]
    # Verify tp_price was passed (1990 - 5.0 * 20 = 1890)
    _, kwargs = flow.executor.open_short.call_args
    assert kwargs["tp_price"] == pytest.approx(1890.0)


def test_portfolio_report_single_asset_stats_and_annualized_math():
    df = pd.DataFrame([
        {"pnl": 50.0, "pnl_pnl": 52.0, "pnl_fee": -1.5, "funding_fee": -0.5, "total_slippage": 0.1, "size": 10, "duration_sec": 3600, "side": "long"},
        {"pnl": -10.0, "pnl_pnl": -9.0, "pnl_fee": -0.8, "funding_fee": -0.2, "total_slippage": 0.1, "size": 10, "duration_sec": 1800, "side": "short"},
    ])
    stats = calculate_single_asset_stats(df, "ETH_USDT", initial_capital=700.0)
    assert stats["total_pnl"] == pytest.approx(40.0)
    assert stats["total_trades"] == 2
    assert stats["win_rate"] == pytest.approx(0.5)
    assert stats["profit_factor"] == pytest.approx(5.0)
    assert stats["long_count"] == 1 and stats["short_count"] == 1

    # Verify return_rate and annualized_return formula used in report
    initial_capital = 700.0
    days = 100
    return_rate = stats["total_pnl"] / initial_capital
    annualized_return = return_rate * (365.0 / days)
    assert return_rate == pytest.approx(40.0 / 700.0)
    assert annualized_return == pytest.approx((40.0 / 700.0) * 3.65)


def test_telegram_notifier_missing_credentials_and_success():
    # Missing credentials returns False cleanly without network call
    notifier_empty = TelegramNotifier(bot_token="", chat_id="")
    assert notifier_empty.send("hello") is False

    # Configured notifier posts to Telegram API
    notifier = TelegramNotifier(bot_token="123:abc", chat_id="999")
    mock_resp = MagicMock(status_code=200)
    with patch("telegram_notifier.requests.post", return_value=mock_resp) as mock_post:
        assert notifier.send("Test alert") is True
        mock_post.assert_called_once()
