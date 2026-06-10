#!/usr/bin/env python3
"""
OKX Historical K-line Data Downloader for 5 Years (Portfolio Sweep: BTC, ETH, SOL, LINK, DOGE).
Downloads 5 years (+30 days warmup) of historical K-lines.
Saves data to backtest/data/ as CSV.
"""

import os
import sys
import time
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "https://www.okx.com/api/v5"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def download_klines(contract: str, interval: str, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """
    Downloads historical K-lines in chunks of 100 bars from end_dt backward to start_dt using OKX API.
    """
    inst_id = contract.replace("_", "-") + "-SWAP"
    okx_bar = "30m" if interval == "30m" else "1H"
    url = f"{BASE_URL}/market/history-candles"
    
    start_ts_ms = int(start_dt.timestamp() * 1000)
    end_ts_ms = int(end_dt.timestamp() * 1000)
    current_after = end_ts_ms + 1000
    
    all_data = []
    session = requests.Session()
    
    print(f"Starting download for {contract} {interval}...")
    
    while True:
        params = {
            "instId": inst_id,
            "bar": okx_bar,
            "limit": 100,
            "after": current_after
        }
        
        try:
            resp = session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"  [{contract} {interval}] HTTP Error {resp.status_code} - retrying in 2s...")
                time.sleep(2)
                continue
                
            res_json = resp.json()
            code = res_json.get("code")
            if code != "0":
                print(f"  [{contract} {interval}] OKX API Error: {res_json.get('msg')} - retrying in 2s...")
                time.sleep(2)
                continue
                
            data = res_json.get("data", [])
            if not data:
                break
                
            chunk_rows = []
            for row in data:
                ts_ms = int(row[0])
                if ts_ms < start_ts_ms:
                    continue
                
                chunk_rows.append({
                    'timestamp': ts_ms // 1000,
                    'open': float(row[1]),
                    'high': float(row[2]),
                    'low': float(row[3]),
                    'close': float(row[4]),
                    'volume': float(row[5])
                })
                
            if chunk_rows:
                chunk_df = pd.DataFrame(chunk_rows)
                all_data.append(chunk_df)
                
                last_ts_ms = int(data[-1][0])
                if len(all_data) % 30 == 0 or last_ts_ms <= start_ts_ms:
                    dt_str = datetime.fromtimestamp(last_ts_ms // 1000, tz=timezone.utc).strftime('%Y-%m-%d')
                    print(f"  [{contract} {interval}] Progress: reached {dt_str}")
                
                if last_ts_ms <= start_ts_ms:
                    break
                    
                current_after = last_ts_ms
            else:
                break
                
            # Sleep slightly to avoid rate limit spikes
            time.sleep(0.15)
            
        except Exception as e:
            print(f"  [{contract} {interval}] Exception: {e} - retrying in 2s...")
            time.sleep(2)
            
    if not all_data:
        return pd.DataFrame()
        
    df = pd.concat(all_data, ignore_index=True)
    df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
    
    start_ts_sec = int(start_dt.timestamp())
    end_ts_sec = int(end_dt.timestamp())
    df = df[(df['timestamp'] >= start_ts_sec) & (df['timestamp'] <= end_ts_sec)].reset_index(drop=True)
    
    return df


def download_and_save(contract: str, interval: str, start_dt: datetime, end_dt: datetime):
    filepath = os.path.join(DATA_DIR, f"{contract}_{interval}_5y.csv")
    
    # Check if the file already exists and has a significant size (over 1MB) to skip downloading if it's already there
    if os.path.exists(filepath) and os.path.getsize(filepath) > 1024 * 1024:
        print(f"⏭️ File {filepath} already exists and is valid. Skipping download.")
        return
        
    df = download_klines(contract, interval, start_dt, end_dt)
    if not df.empty:
        df.to_csv(filepath, index=False)
        print(f"✅ Successfully saved {len(df)} rows to {filepath}")
    else:
        print(f"❌ Failed to download data for {contract} {interval}")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # 5 years + 30 days warmup = 1855 days total
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=5 * 365 + 30)
    
    contracts = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "LINK_USDT", "DOGE_USDT"]
    intervals = ["30m", "1h"]
    
    tasks = []
    for contract in contracts:
        for interval in intervals:
            tasks.append((contract, interval))
            
    print(f"Starting parallel download of 5-year K-line data for {contracts}...")
    
    # Run with max_workers=3 for faster downloading
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for contract, interval in tasks:
            futures.append(executor.submit(download_and_save, contract, interval, start_dt, end_dt))
        
        for f in futures:
            f.result()
            
    print("\n🎉 5-year K-line downloads completed!")


if __name__ == "__main__":
    main()
