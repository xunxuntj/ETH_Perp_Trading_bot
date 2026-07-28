#!/usr/bin/env python3
"""
Optimization Implementation Reference:
1. Volume Delta Ratio calculation (Taker Buy vs Sell Volume).
2. ETF Net Inflow Signal Integration.
3. LightGBM Regime Soft-Classification Model Trainer & Predictor.
"""

import numpy as np
import pandas as pd


def calculate_volume_delta(df_30m: pd.DataFrame) -> pd.Series:
    """
    Calculates Taker Buy Volume Ratio (Volume Delta).
    Volume Delta Ratio = taker_buy_volume / total_volume.
    """
    if 'taker_buy_volume' in df_30m.columns and 'volume' in df_30m.columns:
        delta_ratio = df_30m['taker_buy_volume'] / df_30m['volume'].replace(0, np.nan)
        return delta_ratio.fillna(0.5)
    else:
        # Estimate Volume Delta based on bar close position relative to high-low range
        range_hl = df_30m['high'] - df_30m['low']
        buy_pos = (df_30m['close'] - df_30m['low']) / range_hl.replace(0, np.nan)
        return buy_pos.fillna(0.5)


def calculate_etf_flow_multiplier(etf_inflow_m_usd: float, avg_20d_inflow: float = 200.0,
                                   std_20d_inflow: float = 150.0) -> float:
    """
    Optimization 1: Calculates ETF Flow Risk Multiplier based on daily Net Inflows ($M USD).
    """
    if std_20d_inflow == 0:
        return 1.0

    z_score = (etf_inflow_m_usd - avg_20d_inflow) / std_20d_inflow

    if z_score > 1.2:  # Strong Institutional Accumulation
        return 1.30
    elif z_score < -1.2:  # Strong Institutional Redemption / Outflow
        return 0.70
    else:
        return 1.0


def train_lightgbm_regime_model(df_features: pd.DataFrame, df_labels: pd.Series):
    """
    Optimization 3: LightGBM Machine Learning Regime Soft-Classifier Trainer.
    Saves a lightweight .pkl model for fast <5ms inference in GHA.
    """
    try:
        import lightgbm as lgb
        import joblib

        X = df_features[['chop', 'er', 'atr_z', 'adx']]
        y = df_labels

        model = lgb.LGBMClassifier(
            n_estimators=50,
            max_depth=4,
            learning_rate=0.05,
            random_state=42,
            verbose=-1
        )
        model.fit(X, y)

        model_path = "backtest/regime_lgbm_model.pkl"
        joblib.dump(model, model_path)
        print(f"✅ Successfully trained and saved LightGBM Regime Model to {model_path}")
        return model
    except ImportError:
        print("⚠️ LightGBM or joblib not installed in environment. Install via `pip install lightgbm joblib`.")
        return None
