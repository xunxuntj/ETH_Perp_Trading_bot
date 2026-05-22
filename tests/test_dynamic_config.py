import os
import pytest
from unittest.mock import MagicMock
from config import ENABLE_AUTO_TRADING
from gate_client import GateClient


def test_dynamic_boolean_behavior(monkeypatch):
    # 1. Test default/unset -> False
    monkeypatch.delenv("ENABLE_AUTO_TRADING", raising=False)
    assert not ENABLE_AUTO_TRADING
    assert ENABLE_AUTO_TRADING == False
    assert repr(ENABLE_AUTO_TRADING) == "False"
    assert str(ENABLE_AUTO_TRADING) == "False"

    # 2. Test explicit "false" -> False
    monkeypatch.setenv("ENABLE_AUTO_TRADING", "false")
    assert not ENABLE_AUTO_TRADING
    assert ENABLE_AUTO_TRADING == False

    # 3. Test explicit "true" -> True
    monkeypatch.setenv("ENABLE_AUTO_TRADING", "true")
    assert ENABLE_AUTO_TRADING
    assert ENABLE_AUTO_TRADING == True
    assert repr(ENABLE_AUTO_TRADING) == "True"
    assert str(ENABLE_AUTO_TRADING) == "True"

    # 4. Test logic and negation operators
    monkeypatch.setenv("ENABLE_AUTO_TRADING", "false")
    val_negated = not ENABLE_AUTO_TRADING
    assert val_negated is True

    monkeypatch.setenv("ENABLE_AUTO_TRADING", "true")
    val_negated = not ENABLE_AUTO_TRADING
    assert val_negated is False


def test_mocking_compatibility(monkeypatch):
    # Create a dummy class or import module to simulate monkeypatching
    import config
    assert isinstance(config.ENABLE_AUTO_TRADING, config.DynamicBoolean)

    # Simulate how pytest monkeypatch overrides it with standard bool
    monkeypatch.setattr(config, "ENABLE_AUTO_TRADING", True)
    assert config.ENABLE_AUTO_TRADING is True

    monkeypatch.setattr(config, "ENABLE_AUTO_TRADING", False)
    assert config.ENABLE_AUTO_TRADING is False


class MockResponse:
    def __init__(self, status_code, data_json):
        self.status_code = status_code
        self.data_json = data_json

    def json(self):
        return self.data_json

    def raise_for_status(self):
        pass


def test_get_account_cross_margin(monkeypatch):
    client = GateClient(api_key="mock_key", api_secret="mock_secret")

    # Case 1: List response with USDT having cross_margin_balance
    mock_data_1 = [
        {
            "currency": "USDT",
            "total": "100.0",
            "available": "5.0",
            "cross_margin_balance": "500.0",
            "cross_available": "450.0",
            "unrealised_pnl": "-10.0"
        }
    ]
    monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: MockResponse(200, mock_data_1))
    account = client.get_account()
    assert account["total"] == 500.0
    assert account["available"] == 225.0
    assert account["unrealised_pnl"] == -10.0

    # Case 2: List response with USDT lacking cross_margin_balance but having active cross_available
    mock_data_2 = [
        {
            "currency": "USDT",
            "total": "100.0",
            "available": "0.0",
            "cross_available": "400.0",
            "cross_initial_margin": "80.0",
            "cross_order_margin": "20.0",
            "unrealised_pnl": "5.0"
        }
    ]
    monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: MockResponse(200, mock_data_2))
    account = client.get_account()
    assert account["total"] == 500.0  # 400 + 80 + 20
    assert account["available"] == 200.0
    assert account["unrealised_pnl"] == 5.0

    # Case 3: List response with standard/isolated margin only
    mock_data_3 = [
        {
            "currency": "USDT",
            "total": "300.0",
            "available": "250.0",
            "unrealised_pnl": "10.0"
        }
    ]
    monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: MockResponse(200, mock_data_3))
    account = client.get_account()
    assert account["total"] == 300.0
    assert account["available"] == 125.0
    assert account["unrealised_pnl"] == 10.0

    # Case 4: Dict response with cross_margin_balance
    mock_data_4 = {
        "total": "150.0",
        "available": "10.0",
        "cross_margin_balance": "800.0",
        "cross_available": "750.0",
        "unrealised_pnl": "-25.0"
    }
    monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: MockResponse(200, mock_data_4))
    account = client.get_account()
    assert account["total"] == 800.0
    assert account["available"] == 375.0
    assert account["unrealised_pnl"] == -25.0

    # Case 5: Dict response lacking cross_margin_balance but having active cross margin
    mock_data_5 = {
        "total": "150.0",
        "available": "0.0",
        "cross_available": "650.0",
        "cross_initial_margin": "50.0",
        "cross_order_margin": "10.0",
        "unrealised_pnl": "0.0"
    }
    monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: MockResponse(200, mock_data_5))
    account = client.get_account()
    assert account["total"] == 710.0  # 650 + 50 + 10
    assert account["available"] == 325.0
    assert account["unrealised_pnl"] == 0.0
