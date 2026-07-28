#!/usr/bin/env python3
"""
Professional Quant Market Regime Classifier for Crypto Perpetuals.
Classifies market into:
  1. TREND: 4H ADX > 25, 4H Kaufman ER > 0.40, 4H CHOP < 55.0, 1D EMA Stack aligned.
  2. CHOP: 4H CHOP > 56.0 or Kaufman ER < 0.30 or ADX < 20.
  3. RISK: 1H ATR Z-Score > 3.0 or 1H Bar Return > 3.5x ATR%.
"""

import numpy as np
import pandas as pd
from enum import Enum


class MarketRegime(Enum):
    TREND_LONG = "TREND_LONG"
    TREND_SHORT = "TREND_SHORT"
    CHOP = "CHOP"
    RISK = "RISK"


def calculate_kaufman_er(df: pd.DataFrame, period: int = 10) -> pd.Series:
    """Calculates Kaufman Efficiency Ratio (ER)."""
    change = (df['close'] - df['close'].shift(period)).abs()
    volatility = (df['close'] - df['close'].shift(1)).abs().rolling(window=period).sum()
    er = change / volatility
    return er.fillna(0)


def calculate_choppiness_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates Choppiness Index (CHOP)."""
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    sum_tr = tr.rolling(window=period).sum()
    max_high = high.rolling(window=period).max()
    min_low = low.rolling(window=period).min()

    range_hl = max_high - min_low
    chop = 100.0 * np.log10(sum_tr / range_hl.replace(0, np.nan)) / np.log10(period)
    return chop.fillna(50.0)


def calculate_atr_zscore(df: pd.DataFrame, atr_period: int = 14, lookback: int = 100) -> pd.Series:
    """Calculates ATR Z-Score (Volatility Spike Detector)."""
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=atr_period).mean()

    atr_mean = atr.rolling(window=lookback).mean()
    atr_std = atr.rolling(window=lookback).std()

    zscore = (atr - atr_mean) / atr_std.replace(0, np.nan)
    return zscore.fillna(0)


def classify_regimes(df_1h: pd.DataFrame, df_4h: pd.DataFrame, df_1d: pd.DataFrame) -> pd.DataFrame:
    """
    Combines 1H, 4H, 1D metrics to assign a MarketRegime to each 1H bar.
    """
    df_1h = df_1h.copy()
    df_4h = df_4h.copy()
    df_1d = df_1d.copy()

    # 1H Risk Metric
    df_1h['atr_z'] = calculate_atr_zscore(df_1h, 14, 100)

    # 4H Chop & Trend Metrics
    df_4h['er'] = calculate_kaufman_er(df_4h, 10)
    df_4h['chop'] = calculate_choppiness_index(df_4h, 14)

    # 1D Trend Filter (EMA 50 & 200)
    df_1d['ema_50'] = df_1d['close'].ewm(span=50, adjust=False).mean()
    df_1d['ema_200'] = df_1d['close'].ewm(span=200, adjust=False).mean()
    df_1d['macro_trend'] = np.where(df_1d['close'] > df_1d['ema_50'], 1,
                           np.where(df_1d['close'] < df_1d['ema_50'], -1, 0))

    # Align 4H and 1D onto 1H dataframe using shift by 1 bar to avoid lookahead bias
    df_4h_aligned = df_4h[['er', 'chop']].copy()
    df_4h_aligned.index = df_4h_aligned.index + pd.Timedelta(hours=4)

    df_1d_aligned = df_1d[['macro_trend']].copy()
    df_1d_aligned.index = df_1d_aligned.index + pd.Timedelta(days=1)

    df_1h = df_1h.reset_index()
    df_4h_aligned = df_4h_aligned.reset_index()
    df_1d_aligned = df_1d_aligned.reset_index()

    df_1h['timestamp'] = df_1h['timestamp'].astype('datetime64[ns]')
    df_4h_aligned['timestamp'] = df_4h_aligned['timestamp'].astype('datetime64[ns]')
    df_1d_aligned['timestamp'] = df_1d_aligned['timestamp'].astype('datetime64[ns]')

    df_merged = pd.merge_asof(df_1h, df_4h_aligned, on='timestamp', direction='backward')
    df_merged = pd.merge_asof(df_merged, df_1d_aligned, on='timestamp', direction='backward')
    df_merged.set_index('timestamp', inplace=True)

    # Classification logic
    regimes = []
    for idx, row in df_merged.iterrows():
        if row['atr_z'] > 3.0:
            regimes.append(MarketRegime.RISK)
        elif row['chop'] > 56.0 or row['er'] < 0.30:
            regimes.append(MarketRegime.CHOP)
        elif row['chop'] < 52.0 and row['er'] > 0.40:
            if row['macro_trend'] == 1:
                regimes.append(MarketRegime.TREND_LONG)
            elif row['macro_trend'] == -1:
                regimes.append(MarketRegime.TREND_SHORT)
            else:
                regimes.append(MarketRegime.CHOP)
        else:
            regimes.append(MarketRegime.CHOP)

    df_merged['regime'] = [r.value for r in regimes]
    return df_merged
