import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# Ensure the root path is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

@pytest.fixture
def mock_dependencies():
    with patch('execution_flow.ExecutionFlow') as mock_flow, \
         patch('telegram_notifier.send_telegram_message') as mock_send, \
         patch('gate_client.GateClient') as mock_client:
        yield mock_client, mock_flow, mock_send

def test_main_notification_all_mode(mock_dependencies, monkeypatch):
    mock_client, mock_flow, mock_send = mock_dependencies
    
    # Mock return value of execution flow
    mock_flow_inst = MagicMock()
    mock_flow.return_value = mock_flow_inst
    mock_flow_inst.execute_strategy_and_trade.return_value = {
        "strategy_action": "none",
        "trade_executed": False,
        "message": "Test message: no action"
    }

    # Set configuration
    monkeypatch.setenv("GATE_API_KEY", "test_key")
    monkeypatch.setenv("GATE_API_SECRET", "test_secret")
    monkeypatch.setenv("SIGNAL_NOTIFY_MODE", "all")

    import config
    import main
    import importlib
    importlib.reload(config)
    importlib.reload(main)

    # Run main
    with patch('sys.exit') as mock_exit:
        main.main()
        
    # Since mode is 'all', should send notification even for 'none' action
    mock_send.assert_called_once_with("[ETH_USDT] Test message: no action")


def test_main_notification_operation_mode_no_action(mock_dependencies, monkeypatch):
    mock_client, mock_flow, mock_send = mock_dependencies
    
    mock_flow_inst = MagicMock()
    mock_flow.return_value = mock_flow_inst
    mock_flow_inst.execute_strategy_and_trade.return_value = {
        "strategy_action": "none",
        "trade_executed": False,
        "message": "Test message: no action"
    }

    monkeypatch.setenv("GATE_API_KEY", "test_key")
    monkeypatch.setenv("GATE_API_SECRET", "test_secret")
    monkeypatch.setenv("SIGNAL_NOTIFY_MODE", "operation")

    import config
    import main
    import importlib
    importlib.reload(config)
    importlib.reload(main)

    with patch('sys.exit') as mock_exit:
        main.main()
        
    # Since mode is 'operation' and action is 'none', should NOT send notification
    mock_send.assert_not_called()


def test_main_notification_operation_mode_with_operation(mock_dependencies, monkeypatch):
    mock_client, mock_flow, mock_send = mock_dependencies
    
    mock_flow_inst = MagicMock()
    mock_flow.return_value = mock_flow_inst
    mock_flow_inst.execute_strategy_and_trade.return_value = {
        "strategy_action": "open_long",
        "trade_executed": True,
        "message": "Test message: open long"
    }

    monkeypatch.setenv("GATE_API_KEY", "test_key")
    monkeypatch.setenv("GATE_API_SECRET", "test_secret")
    monkeypatch.setenv("SIGNAL_NOTIFY_MODE", "operation")

    import config
    import main
    import importlib
    importlib.reload(config)
    importlib.reload(main)

    with patch('sys.exit') as mock_exit:
        main.main()
        
    # Since mode is 'operation' and action is 'open_long', should send notification
    mock_send.assert_called_once_with("[ETH_USDT] Test message: open long")


def test_main_notification_report_mode(mock_dependencies, monkeypatch):
    mock_client, mock_flow, mock_send = mock_dependencies
    
    mock_flow_inst = MagicMock()
    mock_flow.return_value = mock_flow_inst
    mock_flow_inst.execute_strategy_and_trade.return_value = {
        "strategy_action": "open_long",
        "trade_executed": True,
        "message": "Test message: open long"
    }

    monkeypatch.setenv("GATE_API_KEY", "test_key")
    monkeypatch.setenv("GATE_API_SECRET", "test_secret")
    monkeypatch.setenv("SIGNAL_NOTIFY_MODE", "report")

    import config
    import main
    import importlib
    importlib.reload(config)
    importlib.reload(main)

    with patch('sys.exit') as mock_exit:
        main.main()
        
    # Since mode is 'report', should NOT send notification
    mock_send.assert_not_called()
