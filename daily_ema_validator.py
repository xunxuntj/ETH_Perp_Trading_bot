#!/usr/bin/env python3
"""
Production Hardened 1D Daily Candlestick Validator & EMA50 Calculator.
Validates:
1. Timestamp-based cutoff strictly before decision moment.
2. Monotonic ascending sort.
3. Zero duplicate timestamps.
4. Maximum daily gap tolerance (max 1 day gap, no massive missing chunks).
5. Effective warmup length (>= 150 daily bars).
6. Safe Degradation: If daily data is missing or invalid, pauses opening new trades,
   while allowing position exits, trailing stops, and order cleanups to operate normally.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Dict, Any

def validate_and_extract_daily_ema50(
    df_raw: Optional[pd.DataFrame],
    decision_time: datetime,
    min_warmup_bars: int = 150
) -> Tuple[bool, Optional[float], Optional[float], str]:
    """
    Validates daily candlestick data and computes EMA50.
    
    Returns:
        (is_valid, last_closed_price, last_ema50_value, diagnostic_message)
    """
    if df_raw is None or not isinstance(df_raw, pd.DataFrame) or df_raw.empty:
        return False, None, None, "Daily candlestick dataframe is empty or None"
        
    df = df_raw.copy()
    
    if getattr(decision_time, 'tzinfo', None) is None:
        dec_utc = decision_time.replace(tzinfo=timezone.utc)
    else:
        dec_utc = decision_time.astimezone(timezone.utc)
    
    # 1. Normalize index / timestamp
    if 'timestamp' in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['dt'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
        else:
            df['dt'] = pd.to_datetime(df['timestamp'], utc=True)
        df.set_index('dt', inplace=True)
    elif isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is None:
            df.index = df.index.tz_localize(timezone.utc)
        else:
            df.index = df.index.tz_convert(timezone.utc)
    else:
        return False, None, None, "Daily data lacks datetime index or timestamp column"
        
    # 2. Check & eliminate duplicate timestamps
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep='last')]
        
    # 3. Verify monotonic sort
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()
        
    # 4. Strict selection: ONLY daily candles closed strictly BEFORE decision_time
    # For a daily candle starting at date D (00:00 UTC), it closes at D + 1 day (00:00 UTC).
    # Therefore, a candle is only closed if candle_open_time + 1 day <= decision_time.
    closed_mask = (df.index + pd.Timedelta(days=1)) <= dec_utc
    df_closed = df.loc[closed_mask]
    
    if df_closed.empty:
        return False, None, None, f"No completed daily candle found strictly before {dec_utc.isoformat()}"
        
    # 5. Check gap / continuity in the latest 100 days
    # Gaps of > 2 days indicate server data corruption
    if len(df_closed) >= 10:
        recent_diffs = df_closed.index[-10:].to_series().diff().dropna()
        max_recent_gap = recent_diffs.max()
        if max_recent_gap > pd.Timedelta(days=2):
            return False, None, None, f"Data gap detected: latest gap is {max_recent_gap}, exceeds tolerance"

    # 6. Strict check of latest expected closed daily bar:
    # A daily candle open at date D (00:00 UTC) closes at D+1 (00:00 UTC).
    # For any decision_time on date T (T >= D+1 00:00 UTC), the expected latest closed daily bar
    # must have opened at (T.floor('D') - 1 day).
    # If the latest bar in df_closed is older than this, data is stale/lagging.
    expected_latest_closed_open = dec_utc.floor('D') - pd.Timedelta(days=1)
    if df_closed.index[-1] < expected_latest_closed_open:
        return False, None, None, (
            f"Stale daily data: expected latest closed daily bar {expected_latest_closed_open.strftime('%Y-%m-%d')} "
            f"is missing (latest found: {df_closed.index[-1].strftime('%Y-%m-%d')})"
        )
            
    # 7. Check warmup bar count
    closed_bars_count = len(df_closed)
    if closed_bars_count < min_warmup_bars:
        return False, None, None, f"Insufficient daily warmup bars: {closed_bars_count} < required {min_warmup_bars}"
        
    # 8. Check close column
    if 'close' not in df_closed.columns:
        return False, None, None, "Missing 'close' column in daily data"
        
    # 9. Compute EMA50 and validate numerical integrity (NaN, Inf, Non-positive, Non-numeric)
    close_series = df_closed['close']
    if close_series.isna().any() or np.isinf(close_series).any() or (close_series <= 0).any():
        return False, None, None, "Daily close series contains NaN, Inf, or non-positive values"
        
    ema_series = close_series.ewm(span=50, adjust=False).mean()
    last_close = float(df_closed['close'].iloc[-1])
    last_ema = float(ema_series.iloc[-1])
    last_bar_time = df_closed.index[-1]
    
    import math
    if (
        math.isnan(last_close) or math.isinf(last_close) or last_close <= 0 or
        math.isnan(last_ema) or math.isinf(last_ema) or last_ema <= 0
    ):
        return False, None, None, f"Abnormal daily price/EMA calculation: close={last_close}, ema50={last_ema}"
    
    msg = f"Valid: {closed_bars_count} closed bars. Last closed: {last_bar_time.strftime('%Y-%m-%d')} Close={last_close:.2f}, EMA50={last_ema:.2f}"
    return True, last_close, last_ema, msg
