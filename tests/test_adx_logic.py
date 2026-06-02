import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
import sys
import os

# Add parent directory to path to import local modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators import calculate_adx, calculate_rma
from strategy import TradingStrategy, TradeResult, Position
from gate_client import GateClient

class TestADXLogic(unittest.TestCase):
    def setUp(self):
        # Create dummy candlestick data (50 rows to satisfy period=16)
        dates = pd.date_range(start="2026-06-01", periods=50, freq="30min")
        
        # Simulate a trending market (ADX will increase)
        highs = [100.0 + i*1.5 for i in range(50)]
        lows = [95.0 + i*1.5 for i in range(50)]
        closes = [98.0 + i*1.5 for i in range(50)]
        
        self.df_trending = pd.DataFrame({
            "high": highs,
            "low": lows,
            "close": closes
        }, index=dates)

        # Simulate a range bound/flat market (ADX will remain low)
        highs_flat = [100.0 + (i % 2)*0.5 for i in range(50)]
        lows_flat = [98.0 - (i % 2)*0.5 for i in range(50)]
        closes_flat = [99.0 + (i % 2)*0.2 for i in range(50)]

        self.df_flat = pd.DataFrame({
            "high": highs_flat,
            "low": lows_flat,
            "close": closes_flat
        }, index=dates)

    def test_calculate_adx_returns_valid_series(self):
        adx = calculate_adx(self.df_trending, period=16)
        self.assertEqual(len(adx), 50)
        # The first 31 elements should be NaN (since period=16 for DMI and 16 for ADX smoothing, 16 + 16 - 1 = 31 bars are required to get the first ADX value)
        self.assertTrue(np.isnan(adx.iloc[0]))
        # The last elements should be valid numbers
        self.assertFalse(np.isnan(adx.iloc[-1]))
        # For trending data, the ADX value should be relatively high
        self.assertGreater(adx.iloc[-1], 20.0)

    def test_calculate_rma_correctness(self):
        series = pd.Series([10.0] * 20)
        rma = calculate_rma(series, period=5)
        # First 4 elements should be NaN
        self.assertTrue(np.isnan(rma.iloc[3]))
        # 5th element should be SMA of first 5 elements = 10.0
        self.assertAlmostEqual(rma.iloc[4], 10.0)
        # All elements should be 10.0
        self.assertAlmostEqual(rma.iloc[-1], 10.0)

    def test_adx_filter_in_strategy_analyze_allows_trend(self):
        # Mock GateClient
        client = MagicMock(spec=GateClient)
        # Mock get_candlesticks to return self.df_trending for both 30m and 1h
        client.get_candlesticks.return_value = self.df_trending
        client.get_account.return_value = {"total": 500, "available": 250, "unrealised_pnl": 0}
        client.get_positions.return_value = None

        with patch("strategy.USE_ADX", True), \
             patch("strategy.ADX_THRESHOLD", 20.0), \
             patch("strategy.ADX_LENGTH", 14), \
             patch("strategy.ADX_TIMEFRAME", "1h"), \
             patch("strategy.load_state", return_value=Position()), \
             patch("strategy.save_state"), \
             patch("strategy.calculate_supertrend") as mock_st, \
             patch("strategy.calculate_dema") as mock_dema:

            # Mock supertrend to trigger a buy signal (direction=1 for last element)
            mock_st.return_value = pd.DataFrame({"supertrend": [90.0]*50, "direction": [1]*50}, index=self.df_trending.index)
            mock_dema.return_value = pd.Series([80.0]*50, index=self.df_trending.index)

            strategy = TradingStrategy(client, contract="SOL_USDT")
            result = strategy.analyze()

            # Should signal open_long because ADX is high in df_trending
            self.assertEqual(result.action, "open_long")
            self.assertIn("ADX 过滤器", result.message)

    def test_adx_filter_in_strategy_analyze_blocks_range(self):
        # Mock GateClient
        client = MagicMock(spec=GateClient)
        # Mock get_candlesticks to return self.df_flat for both 30m and 1h
        client.get_candlesticks.return_value = self.df_flat
        client.get_account.return_value = {"total": 500, "available": 250, "unrealised_pnl": 0}
        client.get_positions.return_value = None

        with patch("strategy.USE_ADX", True), \
             patch("strategy.ADX_THRESHOLD", 30.0), \
             patch("strategy.ADX_LENGTH", 14), \
             patch("strategy.ADX_TIMEFRAME", "1h"), \
             patch("strategy.load_state", return_value=Position()), \
             patch("strategy.save_state"), \
             patch("strategy.calculate_supertrend") as mock_st, \
             patch("strategy.calculate_dema") as mock_dema:

            # Mock supertrend to trigger a buy signal (direction=1)
            mock_st.return_value = pd.DataFrame({"supertrend": [90.0]*50, "direction": [1]*50}, index=self.df_flat.index)
            mock_dema.return_value = pd.Series([80.0]*50, index=self.df_flat.index)

            strategy = TradingStrategy(client, contract="SOL_USDT")
            result = strategy.analyze()

            # Should block the entry signal (action="none") because ADX on flat data is low (below 30)
            self.assertEqual(result.action, "none")
            self.assertIn("过滤中", result.message)

if __name__ == '__main__':
    unittest.main()
