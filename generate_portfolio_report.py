import os
import sys
import json
import datetime
import time
import requests
import numpy as np
import pandas as pd
from typing import Optional, Tuple, Dict, Any

# Load project libraries
from gate_client import GateClient
from telegram_notifier import send_telegram_document, send_telegram_message

# Load config default values
try:
    from config import (
        RISK_MODE as DEFAULT_RISK_MODE, 
        RISK_FIXED_AMOUNT as DEFAULT_RISK_FIXED_AMOUNT,
        RISK_PERCENT as DEFAULT_RISK_PERCENT
    )
except ImportError:
    DEFAULT_RISK_MODE = "fixed"
    DEFAULT_RISK_FIXED_AMOUNT = 5.0
    DEFAULT_RISK_PERCENT = 0.015

# Global Candlestick cache to avoid duplicate API requests
kline_cache = {}

def get_face_value(contract: str) -> float:
    """
    Get contract face value (size multiplier) based on contract name
    """
    c_upper = contract.upper()
    if "ETH" in c_upper:
        return 0.01
    elif "BTC" in c_upper:
        return 0.0001
    elif "SOL" in c_upper:
        return 1.0
    return 0.01

def get_tick_size(contract: str) -> float:
    """
    Get contract tick size (minimum price step)
    """
    c_upper = contract.upper()
    if "ETH" in c_upper:
        return 0.1
    elif "BTC" in c_upper:
        return 0.1
    elif "SOL" in c_upper:
        return 0.01
    return 0.01

def get_kline_close(client: GateClient, contract: str, timestamp: int) -> float:
    """
    Fetch the close price of the 30m candle that aligns with the given timestamp
    """
    if timestamp <= 0:
        return 0.0
        
    aligned_t = (timestamp // 1800) * 1800
    cache_key = f"{contract}_{aligned_t}"
    if cache_key in kline_cache:
        return kline_cache[cache_key]
        
    target_open_t = aligned_t - 1800
    from_t = aligned_t - 3600
    to_t = aligned_t + 3600
    
    BASE_URL = "https://api.gateio.ws/api/v4"
    url = f"{BASE_URL}/futures/usdt/candlesticks"
    params = {
        "contract": contract,
        "interval": "30m",
        "from": from_t,
        "to": to_t,
        "limit": 10
    }
    
    try:
        resp = client.session.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                best_item = None
                min_diff = 999999
                for item in data:
                    item_t = int(item.get('t', 0))
                    diff = abs(item_t - target_open_t)
                    if diff < min_diff:
                        min_diff = diff
                        best_item = item
                if best_item and min_diff < 1800:
                    c_val = float(best_item.get('c', 0))
                    kline_cache[cache_key] = c_val
                    return c_val
    except Exception as e:
        print(f"⚠️ Query KLine Close exception ({contract}, time={timestamp}): {e}")
        
    return 0.0

def get_report_time_window() -> Tuple[datetime.datetime, datetime.datetime, int]:
    """
    获取报告的时间窗口：(start_dt, end_dt, days)
    """
    tz_utc8 = datetime.timezone(datetime.timedelta(hours=8))
    
    try:
        from config import REPORT_START_TIME
    except ImportError:
        REPORT_START_TIME = "2026-06-10 15:00"
        
    end_dt = datetime.datetime.now(datetime.timezone.utc)
    
    # 优先从环境变量获取天数，若指定则按天数推算
    days_str = os.environ.get("REPORT_DAYS")
    if days_str and days_str.strip() != "":
        try:
            days = int(days_str)
            if days > 0:
                start_dt = end_dt - datetime.timedelta(days=days)
                return start_dt, end_dt, days
        except ValueError:
            print(f"⚠️ REPORT_DAYS '{days_str}' is invalid, falling back to REPORT_START_TIME.")
            
    # 否则，从配置中读取具体的启用自动交易时间
    try:
        clean_time_str = REPORT_START_TIME.strip()
        if len(clean_time_str) == 13: # YYYY-MM-DD HH
            dt_naive = datetime.datetime.strptime(clean_time_str, "%Y-%m-%d %H")
        else:
            dt_naive = datetime.datetime.strptime(clean_time_str, "%Y-%m-%d %H:%M")
        
        # 将 naive 时间视作东八区本地时间，然后计算对应的带有时区信息的 datetime
        start_dt = dt_naive.replace(tzinfo=tz_utc8)
    except Exception as e:
        print(f"⚠️ 解析 REPORT_START_TIME '{REPORT_START_TIME}' 失败: {e}，使用默认值 2026-06-10 15:00")
        dt_naive = datetime.datetime.strptime("2026-06-10 15:00", "%Y-%m-%d %H:%M")
        start_dt = dt_naive.replace(tzinfo=tz_utc8)
        
    # 计算实际天数（至少 1 天，向下取整）
    diff_seconds = (end_dt - start_dt).total_seconds()
    days = max(1, int(diff_seconds // 86400))
    return start_dt, end_dt, days

def fetch_all_position_closes(client: GateClient, contract: str, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
    """
    Paginate through Gate.io API to retrieve closed positions for a specific contract
    """
    all_closes = []
    limit = 100
    
    to_timestamp = int(end_dt.timestamp())
    start_timestamp = int(start_dt.timestamp())
    
    BASE_URL = "https://api.gateio.ws/api/v4"
    url_path = "/api/v4/futures/usdt/position_close"
    full_url = f"{BASE_URL}/futures/usdt/position_close"
    
    max_pages = 50
    page = 0
    
    print(f"🔍 Fetching position closes for {contract}...")
    
    last_timestamp = to_timestamp
    while to_timestamp > start_timestamp and page < max_pages:
        page += 1
        query_string = f"contract={contract}&limit={limit}&to={to_timestamp}"
        
        headers = client._sign("GET", url_path, query_string, "")
        params = {"contract": contract, "limit": limit, "to": to_timestamp}
        
        try:
            resp = client.session.get(full_url, params=params, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"❌ API Request failed for {contract} status={resp.status_code}: {resp.text}")
                break
                
            data = resp.json()
            if not data or not isinstance(data, list):
                break
                
            page_closes = []
            min_time_in_page = to_timestamp
            
            for item in data:
                item_contract = item.get('contract', '')
                if item_contract and item_contract != contract:
                    continue
                
                t = int(item.get('time', 0))
                if t < min_time_in_page:
                    min_time_in_page = t
                
                if t < start_timestamp:
                    continue
                    
                close_price = float(item.get('price', 0))
                first_open_time = int(item.get('first_open_time', 0))
                entry_price = float(item.get('long_price', 0) or item.get('short_price', 0) or 0)
                
                side = item.get('side', '')
                if not side:
                    side = 'long' if float(item.get('long_price', 0)) > 0 else 'short'
                
                # Slippage calculations
                sig_open_price = get_kline_close(client, contract, first_open_time) if first_open_time > 0 else 0
                sig_close_price = get_kline_close(client, contract, t)
                
                open_slippage = 0.0
                close_slippage = 0.0
                if sig_open_price > 0 and entry_price > 0:
                    open_slippage = (entry_price - sig_open_price) if side == 'long' else (sig_open_price - entry_price)
                if sig_close_price > 0 and close_price > 0:
                    close_slippage = (sig_close_price - close_price) if side == 'long' else (close_price - sig_close_price)
                
                total_slippage = max(0.0, open_slippage) + max(0.0, close_slippage)
                
                # Funding Fee extraction: pnl = pnl_pnl + pnl_fee + funding_fee => funding_fee = pnl - pnl_pnl - pnl_fee
                pnl = float(item.get('pnl', 0))
                pnl_pnl = float(item.get('pnl_pnl', 0))
                pnl_fee = float(item.get('pnl_fee', 0))
                funding_fee = pnl - pnl_pnl - pnl_fee
                
                duration_sec = (t - first_open_time) if first_open_time > 0 else 0
                
                page_closes.append({
                    'time': t,
                    'datetime': datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M'),
                    'side': side,
                    'pnl': pnl,
                    'pnl_pnl': pnl_pnl,
                    'pnl_fee': pnl_fee,
                    'funding_fee': funding_fee,
                    'text': item.get('text', ''),
                    'entry_price': entry_price,
                    'close_price': close_price,
                    'duration_sec': duration_sec,
                    'open_slippage': open_slippage,
                    'close_slippage': close_slippage,
                    'total_slippage': total_slippage,
                    'size': float(item.get('accumulated_size', 0)),
                    'symbol': contract
                })
            
            if not page_closes:
                break
                
            all_closes.extend(page_closes)
            
            if min_time_in_page >= to_timestamp:
                to_timestamp -= 1
            else:
                to_timestamp = min_time_in_page - 1
                
            if to_timestamp >= last_timestamp:
                to_timestamp = last_timestamp - 1
            last_timestamp = to_timestamp
                
            time.sleep(0.05)
            
        except Exception as e:
            print(f"❌ Exception fetching {contract} page: {str(e)}")
            break
            
    if not all_closes:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_closes)
    df = df.sort_values('time').reset_index(drop=True)
    return df

def format_duration(seconds: float) -> str:
    """
    Format hold duration from seconds to human readable string
    """
    if seconds <= 0:
        return "N/A"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    else:
        return f"{m}m"

def calculate_single_asset_stats(df: pd.DataFrame, symbol: str, initial_capital: float) -> Dict[str, Any]:
    """
    Calculate stats specifically for one asset (BTC or ETH)
    """
    if df.empty:
        return {
            "total_pnl": 0.0,
            "total_trades": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "ratio_avg_win_loss": 0.0,
            "profit_factor": 0.0,
            "max_win": 0.0,
            "max_loss": 0.0,
            "max_losing_streak": 0,
            "total_slippage_tax": 0.0,
            "avg_slippage_ticks": 0.0,
            "total_funding_fee": 0.0,
            "avg_win_hold_str": "N/A",
            "avg_loss_hold_str": "N/A",
            "long_count": 0,
            "short_count": 0
        }

    total_trades = len(df)
    profitable_trades = df[df['pnl'] > 0]
    losing_trades = df[df['pnl'] <= 0]
    
    win_count = len(profitable_trades)
    loss_count = len(losing_trades)
    win_rate = win_count / total_trades if total_trades > 0 else 0.0
    
    avg_win = profitable_trades['pnl'].mean() if win_count > 0 else 0.0
    avg_loss = abs(losing_trades['pnl'].mean()) if loss_count > 0 else 0.0
    
    total_gains = profitable_trades['pnl'].sum()
    total_losses = abs(losing_trades['pnl'].sum())
    profit_factor = total_gains / total_losses if total_losses > 0 else (float('inf') if total_gains > 0 else 0.0)
    ratio_avg_win_loss = avg_win / avg_loss if avg_loss > 0 else (float('inf') if avg_win > 0 else 0.0)
    
    total_pnl = df['pnl'].sum()
    
    # Friction tax
    face_value = get_face_value(symbol)
    tick_size = get_tick_size(symbol)
    
    total_slippage_tax = 0.0
    total_slippage_ticks = 0.0
    for _, row in df.iterrows():
        tax = row['total_slippage'] * row['size'] * face_value
        total_slippage_tax += tax
        total_slippage_ticks += (row['total_slippage'] / tick_size)
        
    avg_slippage_ticks = total_slippage_ticks / total_trades if total_trades > 0 else 0.0
    total_funding_fee = df['funding_fee'].sum()
    
    # Streak logic
    is_loss = df['pnl'] <= 0
    max_losing_streak = is_loss.groupby((~is_loss).cumsum()).cumsum().max()
    if pd.isna(max_losing_streak):
        max_losing_streak = 0
        
    # Hold times
    win_durations = df[df['pnl'] > 0]['duration_sec']
    loss_durations = df[df['pnl'] <= 0]['duration_sec']
    
    avg_win_hold = win_durations.mean() if len(win_durations) > 0 else 0
    avg_loss_hold = loss_durations.mean() if len(loss_durations) > 0 else 0
    
    long_count = len(df[df['side'] == 'long'])
    short_count = len(df[df['side'] == 'short'])
    
    pf_val = None if np.isinf(profit_factor) else profit_factor
    wl_val = None if np.isinf(ratio_avg_win_loss) else ratio_avg_win_loss
    
    return {
        "total_pnl": float(total_pnl),
        "total_trades": int(total_trades),
        "win_count": int(win_count),
        "loss_count": int(loss_count),
        "win_rate": float(win_rate),
        "ratio_avg_win_loss": wl_val,
        "profit_factor": pf_val,
        "max_win": float(df['pnl'].max() if win_count > 0 else 0.0),
        "max_loss": float(df['pnl'].min() if loss_count > 0 else 0.0),
        "max_losing_streak": int(max_losing_streak),
        "total_slippage_tax": float(total_slippage_tax),
        "avg_slippage_ticks": float(avg_slippage_ticks),
        "total_funding_fee": float(total_funding_fee),
        "avg_win_hold_str": format_duration(avg_win_hold),
        "avg_loss_hold_str": format_duration(avg_loss_hold),
        "long_count": int(long_count),
        "short_count": int(short_count)
    }

def generate_portfolio_rules(
    total_pnl: float, win_rate: float, wl_ratio: float, max_dd: float, 
    current_losing_streak: int, btc_stats: dict, eth_stats: dict, 
    pf: float, total_trades: int
) -> Tuple[str, list]:
    """
    Portfolio Rules Diagnostics Engine
    """
    win_rate_pct = win_rate * 100
    is_circuit_broken = False
    
    if current_losing_streak >= 3:
        rule_text = "<span class='text-brand-danger font-bold text-lg'>🚨 触发账户连亏熔断阈值！请检查系统运行状态！</span><br>"
        is_circuit_broken = True
    else:
        if total_pnl > 0:
            rule_text = f"🟢 <b>组合表现</b>: 投资组合在评估期内实现 <b>盈利 (+{total_pnl:.2f} USDT)</b>。 "
        else:
            rule_text = f"🔴 <b>组合表现</b>: 投资组合在评估期内处于 <b>亏损 ({total_pnl:.2f} USDT)</b>。 "
            
    if win_rate_pct < 45 and wl_ratio > 1.8:
        rule_text += "本组合体现典型的 <b>趋势跟踪特性</b> (SuperTrend+ADX)，通过高盈亏比弥补低胜率。在长周期内表现稳定。"
    else:
        rule_text += "多币种分散化降低了整体波动，双币转换平稳。"
        
    risk_advice = []
    
    # Asset Specific Warnings
    for name, stats in [("BTC", btc_stats), ("ETH", eth_stats)]:
        if stats["total_trades"] > 0:
            avg_slip_ticks = stats["avg_slippage_ticks"]
            if avg_slip_ticks > 15.0:
                risk_advice.append(f"<span class='text-brand-danger font-bold'>⚠️ {name} 异常执行滑点！</span> 平均每单滑点 {avg_slip_ticks:.1f} Ticks，滑点税严重侵蚀预期利润，建议调低单笔仓位或优化触发延迟。")
            else:
                risk_advice.append(f"✅ <b>{name} 滑点损耗</b>: 平均每单滑点 {avg_slip_ticks:.1f} Ticks，在正常流动性范围内。")
                
    # Profit Factor Evaluation
    pf_str = f"{pf:.2f}" if pf is not None else "∞"
    if pf is None or pf == float('inf'):
        risk_advice.append("👑 <b>组合获利因子评估</b>: 卓越/无回撤 (PF: ∞) — 期间无任何亏损笔数。")
    elif pf < 1.0:
        risk_advice.append(f"<span class='text-brand-danger font-bold'>💀 组合获利因子评估: 期望值为负 (PF: {pf:.2f})</span> — 策略总盈利未能覆盖总亏损，系统处于实质亏损状态，建议立即停机复盘优化参数。")
    elif pf < 1.25:
        risk_advice.append(f"<span class='text-brand-warning font-bold'>⚠️ 组合获利因子评估: 边际生存 (PF: {pf:.2f})</span> — 扣除手续费及亏损后利润微薄，回撤抵御能力低，生存状态脆弱。")
    elif pf < 1.5:
        risk_advice.append(f"🟡 <b>组合获利因子评估</b>: 合格/基本盈利 (PF: {pf:.2f}) — 策略可实现基本盈亏覆盖，但抗震荡行情侵蚀的边际空间较小。")
    elif pf < 2.0:
        risk_advice.append(f"🟢 <b>组合获利因子评估</b>: 良好/稳健特征 (PF: {pf:.2f}) — 盈利能力良好，收益稳健覆盖风险，具备持续实盘运行基础。")
    else:
        risk_advice.append(f"🚀 <b>组合获利因子评估</b>: 优秀/高效盈利 (PF: {pf:.2f}) — 收益显著优于风险，双资产对冲机制有效运作。")
        
    if current_losing_streak > 0 and not is_circuit_broken:
        risk_advice.append(f"⚠️ <b>连亏警报</b>: 组合当前处于 {current_losing_streak} 连亏中，请关注风控水位。")
        
    return rule_text, risk_advice

def fetch_ai_portfolio_report(df_comb: pd.DataFrame, total_trades: int, win_rate: float, total_pnl: float, 
                             total_fee: float, wl_ratio: float, pf: float, max_dd: float, btc_stats: dict, 
                             eth_stats: dict) -> str:
    """
    AI Portfolio Diagnostics
    """
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ""
        
    api_url = os.environ.get("AI_API_URL", "https://api.openai.com/v1/chat/completions")
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")
    
    recent_summary = df_comb[['datetime', 'symbol', 'side', 'pnl', 'text']].tail(12).to_string()
    
    prompt = f"""
    你是一个资深的数字货币量化交易策略投资经理。下面是某个自动化交易机器人在 Gate.io 的 BTC_USDT 和 ETH_USDT 实盘交易组合评估指标。
    
    评估指标:
    - 组合交易笔数: {total_trades} 笔
    - 组合整体胜率: {win_rate*100:.2f}%
    - 组合累计净盈亏: {total_pnl:.2f} USDT
    - 手续费总额: {total_fee:.2f} USDT
    - 组合获利因子 (Profit Factor): {pf if pf is not None else 'N/A'}
    - 组合最大回撤: {max_dd*100:.2f}%
    
    分币种表现:
    - BTC: 净盈亏 {btc_stats['total_pnl']:.2f} USDT, 交易数 {btc_stats['total_trades']}, 胜率 {btc_stats['win_rate']*100:.2f}%, 获利因子 {btc_stats['profit_factor'] or 'N/A'}, 滑点 {btc_stats['avg_slippage_ticks']:.1f} Ticks
    - ETH: 净盈亏 {eth_stats['total_pnl']:.2f} USDT, 交易数 {eth_stats['total_trades']}, 胜率 {eth_stats['win_rate']*100:.2f}%, 获利因子 {eth_stats['profit_factor'] or 'N/A'}, 滑点 {eth_stats['avg_slippage_ticks']:.1f} Ticks
    
    最近12笔交易历史:
    {recent_summary}
    
    请结合上述真实实盘数据，生成一份简明直击痛点的组合诊断报告：
    1. 指出当前策略在BTC与ETH表现上的优劣异同（例如哪个币种对冲效果好，哪个更适合该策略）；
    2. 评估摩擦损耗占比和胜率组合是否合理；
    3. 给出组合调配或策略参数优化建议。
    字数限制 350 字以内，语气客观、简练、专业。
    """
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3
    }
    
    try:
        resp = requests.post(api_url, headers=headers, json=body, timeout=20)
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip()
        else:
            print(f"⚠️ AI Server error status={resp.status_code}: {resp.text}")
            return f"AI 诊断暂时不可用 (API 返回错误 {resp.status_code})"
    except Exception as e:
        print(f"⚠️ Failed to get AI analysis: {str(e)}")
        return f"AI 诊断暂时不可用 (连接异常)"

def main():
    api_key = os.environ.get("GATE_API_KEY")
    api_secret = os.environ.get("GATE_API_SECRET")
    
    if not api_key or not api_secret:
        print("❌ Error: Missing GATE_API_KEY or GATE_API_SECRET environment variables!")
        sys.exit(1)
        
    start_dt, end_dt, days = get_report_time_window()
    print("=" * 60)
    print(f"🚀 Rebuilding Portfolio Strategy Report...")
    print(f"📅 Evaluation Period: {days} days")
    print(f"⏱ Time Window: {start_dt.strftime('%Y-%m-%d %H:%M %z')} ~ {end_dt.strftime('%Y-%m-%d %H:%M %z')}")
    print("=" * 60)
    
    client = GateClient(api_key, api_secret)

    
    # Query closed positions for BTC & ETH
    df_btc = fetch_all_position_closes(client, "BTC_USDT", start_dt, end_dt)
    df_eth = fetch_all_position_closes(client, "ETH_USDT", start_dt, end_dt)
    
    try:
        acct = client.get_account()
        current_equity = acct.get('total', 1000.0)
    except Exception as e:
        print(f"⚠️ Failed to fetch current account total balance, fallback to 1000.0 U: {e}")
        current_equity = 1000.0
        
    # Check if empty
    btc_empty = df_btc.empty
    eth_empty = df_eth.empty
    
    if btc_empty and eth_empty:
        print("⚠️ No trading data found for BTC and ETH in this period.")
        # Fallback empty structures to render
        btc_stats = calculate_single_asset_stats(pd.DataFrame(), "BTC_USDT", current_equity)
        eth_stats = calculate_single_asset_stats(pd.DataFrame(), "ETH_USDT", current_equity)
        
        report_dict = {
            "days": days,
            "start_date": start_dt.strftime('%Y-%m-%d'),
            "end_date": end_dt.strftime('%Y-%m-%d'),
            "generation_time": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            "total_trades": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "total_fee": 0.0,
            "profit_factor": 0.0,
            "ratio_avg_win_loss": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "current_drawdown": 0.0,
            "current_drawdown_pct": 0.0,
            "max_losing_streak": 0,
            "avg_win_hold_str": "N/A",
            "avg_loss_hold_str": "N/A",
            "total_slippage_tax": 0.0,
            "total_funding_fee": 0.0,
            "friction_ratio": 0.0,
            "chart_labels": [],
            "chart_data": [],
            "btc_chart_data": [],
            "eth_chart_data": [],
            "rule_analysis": "评估期内 BTC 和 ETH 均无任何平仓记录，无法计算组合表现。",
            "risk_advice": ["请核实机器人在该交易周期的运行日志和 API 连通性。"],
            "ai_analysis": "",
            "btc_stats": btc_stats,
            "eth_stats": eth_stats,
            "trades": []
        }
    else:
        # Assign identifiers
        if not btc_empty:
            df_btc['symbol'] = 'BTC_USDT'
        if not eth_empty:
            df_eth['symbol'] = 'ETH_USDT'
            
        # Combine
        dfs_to_concat = []
        if not btc_empty:
            dfs_to_concat.append(df_btc)
        if not eth_empty:
            dfs_to_concat.append(df_eth)
            
        df_comb = pd.concat(dfs_to_concat, ignore_index=True)
        df_comb = df_comb.sort_values('time').reset_index(drop=True)
        
        total_pnl = df_comb['pnl'].sum()
        total_fee = df_comb['pnl_fee'].sum()
        
        # Calculate base capital curve
        initial_capital = current_equity - total_pnl
        if initial_capital <= 0:
            initial_capital = 1000.0
            
        cum_pnl = df_comb['pnl'].cumsum()
        capital_curve = initial_capital + cum_pnl
        
        # Max Drawdown of portfolio
        running_max = capital_curve.cummax()
        drawdown_pct = (capital_curve - running_max) / running_max
        max_dd = drawdown_pct.min()
        
        # Sharpe of portfolio
        comb_returns = df_comb['pnl'] / initial_capital
        std_return = comb_returns.std()
        sharpe = (comb_returns.mean() / std_return * np.sqrt(len(df_comb))) if std_return > 0 and len(df_comb) > 1 else 0.0
        
        # Single stats
        btc_stats = calculate_single_asset_stats(df_btc, "BTC_USDT", initial_capital)
        eth_stats = calculate_single_asset_stats(df_eth, "ETH_USDT", initial_capital)
        
        total_trades = len(df_comb)
        profitable_trades = df_comb[df_comb['pnl'] > 0]
        losing_trades = df_comb[df_comb['pnl'] <= 0]
        
        win_count = len(profitable_trades)
        loss_count = len(losing_trades)
        win_rate = win_count / total_trades if total_trades > 0 else 0.0
        
        avg_win = profitable_trades['pnl'].mean() if win_count > 0 else 0.0
        avg_loss = abs(losing_trades['pnl'].mean()) if loss_count > 0 else 0.0
        
        total_gains = profitable_trades['pnl'].sum()
        total_losses = abs(losing_trades['pnl'].sum())
        profit_factor = total_gains / total_losses if total_losses > 0 else (float('inf') if total_gains > 0 else 0.0)
        ratio_avg_win_loss = avg_win / avg_loss if avg_loss > 0 else (float('inf') if avg_win > 0 else 0.0)
        
        total_funding_fee = df_comb['funding_fee'].sum()
        
        # Friction taxes
        total_slippage_tax = btc_stats['total_slippage_tax'] + eth_stats['total_slippage_tax']
        friction_ratio = abs(total_slippage_tax + total_funding_fee) / (total_gains + 1.0)
        
        # Combined streaks
        is_loss = df_comb['pnl'] <= 0
        max_losing_streak = is_loss.groupby((~is_loss).cumsum()).cumsum().max()
        if pd.isna(max_losing_streak):
            max_losing_streak = 0
            
        current_losing_streak = 0
        for val in reversed(df_comb['pnl'].tolist()):
            if val <= 0:
                current_losing_streak += 1
            else:
                break
                
        current_equity = capital_curve.iloc[-1]
        peak_equity = max(initial_capital, capital_curve.max())
        current_drawdown = min(0.0, current_equity - peak_equity)
        current_drawdown_pct = current_drawdown / peak_equity if peak_equity > 0 else 0.0
        
        # Average hold times
        win_durations = df_comb[df_comb['pnl'] > 0]['duration_sec']
        loss_durations = df_comb[df_comb['pnl'] <= 0]['duration_sec']
        avg_win_hold = win_durations.mean() if len(win_durations) > 0 else 0
        avg_loss_hold = loss_durations.mean() if len(loss_durations) > 0 else 0
        
        # R multiples - 精准计算：根据每个仓位入场时的账户权益动态计算 R 值，支持重叠仓位
        r_multiples = []
        for _, row in df_comb.iterrows():
            pnl = row['pnl']
            duration = row.get('duration_sec', 0)
            entry_time = row['time'] - duration if duration > 0 else row['time']
            # 找到在该仓位入场之前已经平仓的所有交易的累计盈亏
            prior_pnl_sum = df_comb[df_comb['time'] < entry_time]['pnl'].sum()
            equity_at_entry = initial_capital + prior_pnl_sum
            
            if DEFAULT_RISK_MODE == "percent":
                one_r = equity_at_entry * DEFAULT_RISK_PERCENT
            else:
                one_r = DEFAULT_RISK_FIXED_AMOUNT
                
            if one_r <= 0:
                one_r = 5.0
            r_multiples.append(pnl / one_r)
            
        # Chart construction (multi-line)
        chart_labels = ["开始"]
        chart_data = [0.0]
        btc_chart_data = [0.0]
        eth_chart_data = [0.0]
        
        btc_cum = 0.0
        eth_cum = 0.0
        
        for _, row in df_comb.iterrows():
            pnl = row['pnl']
            symbol = row['symbol']
            dt_str = row['datetime']
            
            if symbol == 'BTC_USDT':
                btc_cum += pnl
            elif symbol == 'ETH_USDT':
                eth_cum += pnl
                
            chart_labels.append(dt_str)
            chart_data.append(btc_cum + eth_cum)
            btc_chart_data.append(btc_cum)
            eth_chart_data.append(eth_cum)
            
        # Unified trades list
        trades_list = []
        for idx, row in df_comb.iterrows():
            trades_list.append({
                "datetime": row['datetime'],
                "symbol": row['symbol'],
                "side": row['side'],
                "pnl": row['pnl_pnl'],
                "fee": row['pnl_fee'],
                "net_pnl": row['pnl'],
                "entry_price": row['entry_price'],
                "close_price": row['close_price'],
                "size": row['size'],
                "duration_str": format_duration(row['duration_sec']),
                "r_multiple": r_multiples[idx],
                "text": row['text']
            })
            
        # Diagnostics
        rule_analysis, risk_advice = generate_portfolio_rules(
            total_pnl, win_rate, ratio_avg_win_loss, max_dd, 
            current_losing_streak, btc_stats, eth_stats, profit_factor, total_trades
        )
        
        ai_analysis = fetch_ai_portfolio_report(
            df_comb, total_trades, win_rate, total_pnl, total_fee, 
            ratio_avg_win_loss, profit_factor, max_dd, btc_stats, eth_stats
        )
        
        pf_val = None if np.isinf(profit_factor) else profit_factor
        wl_val = None if np.isinf(ratio_avg_win_loss) else ratio_avg_win_loss
        
        report_dict = {
            "days": days,
            "start_date": start_dt.strftime('%Y-%m-%d'),
            "end_date": end_dt.strftime('%Y-%m-%d'),
            "generation_time": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            "total_trades": total_trades,
            "win_count": int(win_count),
            "loss_count": int(loss_count),
            "win_rate": float(win_rate),
            "total_pnl": float(total_pnl),
            "total_fee": float(total_fee),
            "profit_factor": pf_val,
            "ratio_avg_win_loss": wl_val,
            "max_drawdown": float(max_dd),
            "sharpe_ratio": float(sharpe),
            "current_drawdown": float(current_drawdown),
            "current_drawdown_pct": float(current_drawdown_pct),
            "max_losing_streak": int(max_losing_streak),
            "avg_win_hold_str": format_duration(avg_win_hold),
            "avg_loss_hold_str": format_duration(avg_loss_hold),
            "total_slippage_tax": float(total_slippage_tax),
            "total_funding_fee": float(total_funding_fee),
            "friction_ratio": float(friction_ratio),
            "chart_labels": chart_labels,
            "chart_data": chart_data,
            "btc_chart_data": btc_chart_data,
            "eth_chart_data": eth_chart_data,
            "rule_analysis": rule_analysis,
            "risk_advice": risk_advice,
            "ai_analysis": ai_analysis,
            "btc_stats": btc_stats,
            "eth_stats": eth_stats,
            "trades": trades_list[::-1]  # reverse chron for audit display
        }
        
    # HTML Render
    template_path = os.path.join(os.path.dirname(__file__), "templates", "portfolio_report_template.html")
    if not os.path.exists(template_path):
        print(f"❌ Error: Cannot find template file: {template_path}")
        sys.exit(1)
        
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    report_json_str = json.dumps(report_dict, ensure_ascii=False)
    output_html_content = html_content.replace("__PORTFOLIO_REPORT_DATA_PLACEHOLDER__", report_json_str)
    
    start_date_str = start_dt.strftime("%Y%m%d")
    end_date_str = end_dt.strftime("%Y%m%d")
    report_filename = f"portfolio_report_{start_date_str}_to_{end_date_str}.html"
    report_filepath = os.path.join(os.path.dirname(__file__), report_filename)
    
    with open(report_filepath, "w", encoding="utf-8") as f:
        f.write(output_html_content)
        
    print(f"✅ Portfolio HTML Report rendered and saved: {report_filepath}")
    
    # Send Telegram Document and Caption
    pnl_sign = "+" if report_dict['total_pnl'] >= 0 else ""
    pf_str = f"{report_dict['profit_factor']:.2f}" if report_dict['profit_factor'] is not None else "∞"
    
    btc_p_sign = "+" if btc_stats['total_pnl'] >= 0 else ""
    eth_p_sign = "+" if eth_stats['total_pnl'] >= 0 else ""
    
    streak_warning = ""
    if report_dict['max_losing_streak'] >= 3:
        streak_warning = f"🔴 触发过连亏熔断阈值！最大连亏: {report_dict['max_losing_streak']} 次"
    else:
        streak_warning = f"🟢 无熔断风险 (最大连亏: {report_dict['max_losing_streak']} 次)"
        
    diagnostic_summary = "账户双币组合运行正常，滑点与资金费均在预算空间内。"
    if report_dict['max_losing_streak'] >= 3:
        diagnostic_summary = "🚨 警告：双币大盘曾触发过熔断阈值，请密切核实订单详情！"
    elif btc_stats['avg_slippage_ticks'] > 15.0 or eth_stats['avg_slippage_ticks'] > 15.0:
        diagnostic_summary = "⚠️ 警告：某一资产滑点偏高，流动性异常，滑点损耗加大。"
    elif report_dict['profit_factor'] is not None and report_dict['profit_factor'] < 1.15 and report_dict['total_trades'] > 10:
        diagnostic_summary = "💀 组合总体期望值为负，获利因子偏低，建议立即停机评估策略参数。"
        
    tg_caption = f"""📊 <b>[Gate.io 实盘双币战报]</b>
⏱ <b>统计周期</b>：自 {start_dt.strftime('%m-%d')} 至 {end_dt.strftime('%m-%d')} ({days} 天)

💰 <b>【组合盈亏大盘】</b>
• 账户组合净利： <b>{pnl_sign}{report_dict['total_pnl']:.2f} U</b> (已扣手续费/资金费)
• 组合获利因子： <b>{pf_str}</b> (健康阀值 &gt; 1.15)
• 组合综合胜率： <b>{report_dict['win_rate']*100:.1f}%</b> (赢: {report_dict['win_count']} | 输: {report_dict['loss_count']} | 共: {report_dict['total_trades']} 笔)
• 组合最大回撤： <b>{report_dict['max_drawdown']*100:.1f}%</b>
• 组合估算夏普： <b>{report_dict['sharpe_ratio']:.2f}</b>

📈 <b>【币种表现拆分】</b>
• <b>BTC_USDT</b>:
  - 净盈亏: <b>{btc_p_sign}{btc_stats['total_pnl']:.2f} U</b>
  - 胜率: <b>{btc_stats['win_rate']*100:.1f}%</b> (赢 {btc_stats['win_count']} | 输 {btc_stats['loss_count']} | 交易 {btc_stats['total_trades']} 笔)
  - 获利因子: <b>{f"{btc_stats['profit_factor']:.2f}" if btc_stats['profit_factor'] is not None else "∞"}</b>
  - 平均滑点: <b>{btc_stats['total_slippage_tax']/max(1, btc_stats['total_trades']):.2f} U</b> (约 {btc_stats['avg_slippage_ticks']:.1f} Ticks)
• <b>ETH_USDT</b>:
  - 净盈亏: <b>{eth_p_sign}{eth_stats['total_pnl']:.2f} U</b>
  - 胜率: <b>{eth_stats['win_rate']*100:.1f}%</b> (赢 {eth_stats['win_count']} | 输 {eth_stats['loss_count']} | 交易 {eth_stats['total_trades']} 笔)
  - 获利因子: <b>{f"{eth_stats['profit_factor']:.2f}" if eth_stats['profit_factor'] is not None else "∞"}</b>
  - 平均滑点: <b>{eth_stats['total_slippage_tax']/max(1, eth_stats['total_trades']):.2f} U</b> (约 {eth_stats['avg_slippage_ticks']:.1f} Ticks)

🛡️ <b>【风控与摩擦损耗】</b>
• 组合连亏水位： <b>{streak_warning}</b>
• 组合滑点税额： <b>{report_dict['total_slippage_tax']:.2f} U</b>
• 组合资金费用： <b>{report_dict['total_funding_fee']:.2f} U</b>
• 摩擦损耗比例： <b>{report_dict['friction_ratio']*100:.1f}%</b>

👮‍♂️ <b>【风控官诊断】</b>
<i>{diagnostic_summary}</i>

💡 <i>请点击下方 HTML 文件在浏览器中打开，查看双币交互折线图、并排对比表与全部平仓明细。</i>"""

    success = send_telegram_document(report_filepath, caption=tg_caption)
    if success:
        print("📱 Portfolio Report Document successfully pushed to Telegram!")
    else:
        print("❌ Warning: Failed to send Portfolio Report to Telegram!")
        
    print("🎉 Portfolio report workflow complete.")

if __name__ == "__main__":
    main()
