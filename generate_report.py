import os
import sys
import json
import datetime
import time
import requests
import numpy as np
import pandas as pd
from typing import Optional

# 载入项目库
from gate_client import GateClient
from telegram_notifier import send_telegram_document, send_telegram_message

# 载入项目配置中的配置项
try:
    from config import (
        SYMBOL as DEFAULT_SYMBOL, 
        RISK_MODE as DEFAULT_RISK_MODE, 
        RISK_FIXED_AMOUNT as DEFAULT_RISK_FIXED_AMOUNT,
        RISK_PERCENT as DEFAULT_RISK_PERCENT
    )
except ImportError:
    DEFAULT_SYMBOL = "SOL_USDT"
    DEFAULT_RISK_MODE = "fixed"
    DEFAULT_RISK_FIXED_AMOUNT = 10.0
    DEFAULT_RISK_PERCENT = 0.02


# 本地 K 线查询缓存，防止重复请求 API
kline_cache = {}


def get_face_value(contract: str) -> float:
    """
    根据合约自动匹配面值
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
    智能获取交易对的最小 Tick 大小，用于滑点 Ticks 计算
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
    根据给定的平仓/开仓时间戳，向下对齐到 30m 周期边界，获取该周期的收盘价 Close 作为理论信号价
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
        print(f"⚠️ 查询 K 线收盘价异常 (time={timestamp}): {e}")
        
    return 0.0


def calculate_default_days() -> int:
    """
    计算从 2026年6月2日 到当前日期的实际天数
    如果结果小于等于 0，则默认返回 1 天
    """
    base_date = datetime.datetime(2026, 6, 2, tzinfo=datetime.timezone.utc)
    current_date = datetime.datetime.now(datetime.timezone.utc)
    
    base_day = datetime.datetime(base_date.year, base_date.month, base_date.day, tzinfo=datetime.timezone.utc)
    current_day = datetime.datetime(current_date.year, current_date.month, current_date.day, tzinfo=datetime.timezone.utc)
    
    diff_days = (current_day - base_day).days
    return max(1, diff_days)


def get_report_config():
    """
    从环境变量中提取报告配置参数，并处理默认值
    """
    symbol = os.environ.get("REPORT_SYMBOL")
    if not symbol or symbol.strip() == "":
        symbol = DEFAULT_SYMBOL
    symbol = symbol.strip().upper()
        
    days_str = os.environ.get("REPORT_DAYS")
    if not days_str or days_str.strip() == "":
        days = calculate_default_days()
    else:
        try:
            days = int(days_str)
            if days <= 0:
                days = calculate_default_days()
        except ValueError:
            print(f"⚠️ 环境变量 REPORT_DAYS 的值 '{days_str}' 不是有效整数，已切换为默认值天数。")
            days = calculate_default_days()
            
    return symbol, days


def fetch_all_position_closes(client: GateClient, contract: str, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
    """
    分页抓取指定时间范围内的所有平仓记录
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
    
    print(f"🔍 启动分页获取 {contract} 平仓记录...")
    print(f"📅 查询时间区间: {start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} ~ {end_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    last_timestamp = to_timestamp
    
    while to_timestamp > start_timestamp and page < max_pages:
        page += 1
        query_string = f"contract={contract}&limit={limit}&to={to_timestamp}"
        
        headers = client._sign("GET", url_path, query_string, "")
        params = {"contract": contract, "limit": limit, "to": to_timestamp}
        
        try:
            # 🚨 必须设置 timeout 防止在 Actions 中无限挂起
            resp = client.session.get(full_url, params=params, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"❌ API 请求失败 status={resp.status_code}: {resp.text}")
                break
                
            data = resp.json()
            if not data or not isinstance(data, list):
                break
                
            page_closes = []
            min_time_in_page = to_timestamp
            
            for item in data:
                # 1. 确保标的合约名称匹配 (防止 API 返回其他合约数据)
                item_contract = item.get('contract', '')
                if item_contract and item_contract != contract:
                    continue
                
                t = int(item.get('time', 0))
                if t < min_time_in_page:
                    min_time_in_page = t
                
                # 剔除早于我们设定起始时间的数据
                if t < start_timestamp:
                    continue
                    
                # 提取平仓均价和开仓时间
                close_price = float(item.get('price', 0))
                first_open_time = int(item.get('first_open_time', 0))
                entry_price = float(item.get('long_price', 0) or item.get('short_price', 0) or 0)
                
                # 确定方向：优先读取 API 返回的官方 side 字段，否则使用 long_price 兜底判断
                side = item.get('side', '')
                if not side:
                    side = 'long' if float(item.get('long_price', 0)) > 0 else 'short'
                
                # 滑点计算 (需要请求 K 线，加入防错)
                sig_open_price = get_kline_close(client, contract, first_open_time) if first_open_time > 0 else 0
                sig_close_price = get_kline_close(client, contract, t)
                
                open_slippage = 0.0
                close_slippage = 0.0
                if sig_open_price > 0 and entry_price > 0:
                    open_slippage = (entry_price - sig_open_price) if side == 'long' else (sig_open_price - entry_price)
                if sig_close_price > 0 and close_price > 0:
                    close_slippage = (sig_close_price - close_price) if side == 'long' else (close_price - sig_close_price)
                
                total_slippage = max(0.0, open_slippage) + max(0.0, close_slippage) # 统计负滑点
                
                # 资金费率推算： 净利润 (pnl) = 仓位盈亏 (pnl_pnl) + 手续费 (pnl_fee) + 资金费 (funding)
                # 资金费 = pnl - pnl_pnl - pnl_fee
                pnl = float(item.get('pnl', 0))
                pnl_pnl = float(item.get('pnl_pnl', 0))
                pnl_fee = float(item.get('pnl_fee', 0))
                funding_fee = pnl - pnl_pnl - pnl_fee
                
                # 持仓时长 (秒)
                duration_sec = (t - first_open_time) if first_open_time > 0 else 0
                
                page_closes.append({
                    'time': t,
                    'datetime': datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M'),
                    'side': side,
                    'pnl': pnl,  # 净盈亏 (已扣手续费/资金费)
                    'pnl_pnl': pnl_pnl,  # 盘面盈亏
                    'pnl_fee': pnl_fee,  # 手续费
                    'funding_fee': funding_fee,  # 推导的资金费率
                    'text': item.get('text', ''),
                    'entry_price': entry_price,
                    'close_price': close_price,
                    'duration_sec': duration_sec,
                    'open_slippage': open_slippage,
                    'close_slippage': close_slippage,
                    'total_slippage': total_slippage,
                    'size': float(item.get('accumulated_size', 0))
                })
            
            if not page_closes:
                break
                
            all_closes.extend(page_closes)
            
            # 翻页
            if min_time_in_page >= to_timestamp:
                to_timestamp -= 1
            else:
                to_timestamp = min_time_in_page - 1
                
            if to_timestamp >= last_timestamp:
                to_timestamp = last_timestamp - 1
            last_timestamp = to_timestamp
                
            print(f"   已加载第 {page} 页，总计拉取 {len(all_closes)} 笔平仓记录...")
            time.sleep(0.1)
            
        except Exception as e:
            print(f"❌ 分页抓取时发生异常: {str(e)}")
            break
            
    if not all_closes:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_closes)
    df = df.sort_values('time').reset_index(drop=True)
    return df


def format_duration(seconds: float) -> str:
    """
    格式化持仓秒数为人性化字符串
    """
    if seconds <= 0:
        return "N/A"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    else:
        return f"{m}m"


def calculate_metrics_to_json(df: pd.DataFrame, symbol: str, days: int, start_dt: datetime.datetime, end_dt: datetime.datetime, current_equity: float) -> dict:
    """
    计算完整策略指标与隐形磨损数据
    """
    if df.empty:
        return {
            "symbol": symbol,
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
            "max_win": 0.0,
            "max_loss": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "long_count": 0,
            "short_count": 0,
            "chart_labels": [],
            "chart_data": [],
            "rule_analysis": "无交易数据，无法生成分析报告。",
            "risk_advice": ["请确认在此期间该交易对是否有实盘交易。"],
            "ai_analysis": "",
            "total_slippage_tax": 0.0,
            "avg_slippage_u": 0.0,
            "avg_slippage_ticks": 0.0,
            "total_funding_fee": 0.0,
            "friction_ratio": 0.0,
            "max_losing_streak": 0,
            "current_losing_streak": 0,
            "current_drawdown": 0.0,
            "current_drawdown_pct": 0.0,
            "avg_win_hold_str": "N/A",
            "avg_loss_hold_str": "N/A",
            "trades": []
        }
        
    total_trades = len(df)
    profitable_trades = df[df['pnl'] > 0]
    losing_trades = df[df['pnl'] <= 0]
    
    win_count = len(profitable_trades)
    loss_count = len(losing_trades)
    win_rate = win_count / total_trades
    
    avg_win = profitable_trades['pnl'].mean() if win_count > 0 else 0
    avg_loss = abs(losing_trades['pnl'].mean()) if loss_count > 0 else 0
    
    total_gains = profitable_trades['pnl'].sum()
    total_losses = abs(losing_trades['pnl'].sum())
    profit_factor = total_gains / total_losses if total_losses > 0 else (float('inf') if total_gains > 0 else 0)
    ratio_avg_win_loss = avg_win / avg_loss if avg_loss > 0 else (float('inf') if avg_win > 0 else 0)
    
    total_pnl = df['pnl'].sum()
    total_fee = df['pnl_fee'].sum()
    
    # 1. 倒推初始本金与资产曲线
    initial_capital = current_equity - total_pnl
    if initial_capital <= 0:
        initial_capital = 1000.0  # 兜底
        
    cum_pnl = df['pnl'].cumsum()
    capital_curve = initial_capital + cum_pnl
    
    # 最大回撤率
    running_max = capital_curve.cummax()
    drawdown_pct = (capital_curve - running_max) / running_max
    max_dd = drawdown_pct.min()
    
    # 夏普比率
    trades_returns = df['pnl'] / initial_capital
    std_return = trades_returns.std()
    sharpe = (trades_returns.mean() / std_return * np.sqrt(total_trades)) if std_return > 0 and total_trades > 1 else 0
    
    # 2. 隐形摩擦审计 (Friction Audit)
    # 计算滑点 (U值) = 滑点价差 * size * face_value
    face_value = get_face_value(symbol)
    tick_size = get_tick_size(symbol)
    
    total_slippage_tax = 0.0
    total_slippage_ticks = 0.0
    for _, row in df.iterrows():
        tax = row['total_slippage'] * row['size'] * face_value
        total_slippage_tax += tax
        total_slippage_ticks += (row['total_slippage'] / tick_size)
        
    avg_slippage_ticks = total_slippage_ticks / total_trades if total_trades > 0 else 0
    avg_slippage_u = total_slippage_tax / total_trades if total_trades > 0 else 0.0
    total_funding_fee = df['funding_fee'].sum()
    
    # 合计摩擦占总毛利润比例
    friction_ratio = abs(total_slippage_tax + total_funding_fee) / (total_gains + 1.0)
    
    # 3. 风控与生存极限
    is_loss = df['pnl'] <= 0
    max_losing_streak = is_loss.groupby((~is_loss).cumsum()).cumsum().max()
    if pd.isna(max_losing_streak):
        max_losing_streak = 0
        
    current_losing_streak = 0
    for val in reversed(df['pnl'].tolist()):
        if val <= 0:
            current_losing_streak += 1
        else:
            break
            
    current_equity = capital_curve.iloc[-1]
    peak_equity = max(initial_capital, capital_curve.max())
    current_drawdown = min(0.0, current_equity - peak_equity)
    current_drawdown_pct = current_drawdown / peak_equity if peak_equity > 0 else 0
    
    # 4. 持仓时长侧写
    win_durations = df[df['pnl'] > 0]['duration_sec']
    loss_durations = df[df['pnl'] <= 0]['duration_sec']
    
    avg_win_hold = win_durations.mean() if len(win_durations) > 0 else 0
    avg_loss_hold = loss_durations.mean() if len(loss_durations) > 0 else 0
    
    avg_win_hold_str = format_duration(avg_win_hold)
    avg_loss_hold_str = format_duration(avg_loss_hold)
    
    # 5. 动态计算 R 倍数
    r_multiples = []
    current_cap = initial_capital
    for _, row in df.iterrows():
        pnl = row['pnl']
        if DEFAULT_RISK_MODE == "percent":
            one_r = current_cap * DEFAULT_RISK_PERCENT
        else:
            one_r = DEFAULT_RISK_FIXED_AMOUNT
            
        if one_r <= 0:
            one_r = 10.0
        r_multiples.append(pnl / one_r)
        current_cap += pnl
        
    # 6. 高阶规则诊断
    rule_analysis, risk_advice = generate_advanced_rules(
        total_pnl, win_rate, ratio_avg_win_loss, max_dd, total_fee, 
        current_losing_streak, avg_slippage_ticks, profit_factor, total_trades
    )
    
    # AI 智能分析 (可选)
    ai_analysis = fetch_ai_report(df, total_trades, win_rate, total_pnl, total_fee, ratio_avg_win_loss, profit_factor, max_dd, sharpe)
    
    # 多空计数
    long_count = len(df[df['side'] == 'long'])
    short_count = len(df[df['side'] == 'short'])
    
    chart_labels = df['datetime'].tolist()
    chart_data = [0] + cum_pnl.tolist()
    chart_labels = ["开始"] + chart_labels
    
    # 转换交易历史列表
    trades_list = []
    for idx, row in df.iterrows():
        trades_list.append({
            "datetime": row['datetime'],
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
        
    pf_val = None if profit_factor == float('inf') or np.isinf(profit_factor) else profit_factor
    wl_val = None if ratio_avg_win_loss == float('inf') or np.isinf(ratio_avg_win_loss) else ratio_avg_win_loss
    
    return {
        "symbol": symbol,
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
        "max_win": float(df['pnl'].max()),
        "max_loss": float(df['pnl'].min()),
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),
        "long_count": int(long_count),
        "short_count": int(short_count),
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "rule_analysis": rule_analysis,
        "risk_advice": risk_advice,
        "ai_analysis": ai_analysis,
        "total_slippage_tax": float(total_slippage_tax),
        "avg_slippage_u": float(avg_slippage_u),
        "avg_slippage_ticks": float(avg_slippage_ticks),
        "total_funding_fee": float(total_funding_fee),
        "friction_ratio": float(friction_ratio),
        "max_losing_streak": int(max_losing_streak),
        "current_losing_streak": int(current_losing_streak),
        "current_drawdown": float(current_drawdown),
        "current_drawdown_pct": float(current_drawdown_pct),
        "avg_win_hold_str": avg_win_hold_str,
        "avg_loss_hold_str": avg_loss_hold_str,
        "trades": trades_list[::-1]
    }


def generate_advanced_rules(total_pnl: float, win_rate: float, wl_ratio: float, max_dd: float, total_fee: float, 
                           current_losing_streak: int, avg_slippage_ticks: float, pf: float, total_trades: int):
    """
    高阶规则引擎，融入风控官的咆哮规则
    """
    win_rate_pct = win_rate * 100
    
    is_circuit_broken = False
    if current_losing_streak >= 3:
        rule_text = "<span style='color: #ff3e60; font-weight: bold; font-size: 1.1rem;'>🚨 触发连亏熔断阈值！请检查服务器是否已自动切断 API！</span><br>"
        is_circuit_broken = True
    else:
        if total_pnl > 0:
            rule_text = f"🟢 **总体表现**: 策略在评估期内实现**盈利 (+{total_pnl:.2f} USDT)**。 "
        else:
            rule_text = f"🔴 **总体表现**: 策略在评估期内处于**亏损 ({total_pnl:.2f} USDT)**。 "
            
    if win_rate_pct < 45 and wl_ratio > 1.8:
        rule_text += "策略呈现典型**趋势跟踪**架构 (SuperTrend+ADX)，通过大盈亏比弥补胜率的不足。震荡期出现连亏或低效率属正常规律。"
    else:
        rule_text += "策略运行平稳，多空转换健康。"
        
    risk_advice = []
    
    if avg_slippage_ticks > 15.0:
        risk_advice.append(f"<span style='color: #ff3e60; font-weight: bold;'>⚠️ 异常流动性警告！平均滑点 ({avg_slippage_ticks:.1f} Ticks) 已超出 15 Ticks 预警线，滑点税严重侵蚀预期利润，建议调低单笔仓位或暂停交易。</span>")
    else:
        risk_advice.append(f"✅ **流动性滑点**: 平均每单滑点 {avg_slippage_ticks:.1f} Ticks，在正常流动性范围内。")
        
    # 获利因子分档评估
    pf_str = f"{pf:.2f}" if pf != float('inf') else "∞"
    if pf == float('inf') or np.isinf(pf) or np.isnan(pf):
        risk_advice.append(f"👑 **获利因子评估**: 卓越/无回撤 (PF: {pf_str}) — 期间无任何亏损笔数。注：若交易笔数极少，需谨防样本偏差。")
    elif pf < 1.0:
        risk_advice.append(f"<span style='color: #ff3e60; font-weight: bold;'>💀 获利因子评估: 期望值为负/极差 (PF: {pf:.2f}) — 策略总盈利未能覆盖总亏损，系统处于实质亏损状态，建议立即停机复盘优化。</span>")
    elif pf < 1.25:
        risk_advice.append(f"<span style='color: #ffaa00; font-weight: bold;'>⚠️ 获利因子评估: 边际生存/较差 (PF: {pf:.2f}) — 扣除手续费及亏损后利润微薄，回撤抵御能力低，生存状态脆弱。</span>")
    elif pf < 1.5:
        risk_advice.append(f"🟡 **获利因子评估**: 合格/基本盈利 (PF: {pf:.2f}) — 策略可实现基本盈亏覆盖，但抗震荡行情侵蚀的边际空间较小。")
    elif pf < 2.0:
        risk_advice.append(f"🟢 **获利因子评估**: 良好/稳健特征 (PF: {pf:.2f}) — 盈利能力良好，收益稳健覆盖风险，具备持续实盘运行基础。")
    elif pf < 3.0:
        risk_advice.append(f"🚀 **获利因子评估**: 优秀/高效盈利 (PF: {pf:.2f}) — 收益显著优于风险，策略对当前行情具有明显期望优势。")
    else:
        risk_advice.append(f"👑 **获利因子评估**: 卓越/异常表现 (PF: {pf:.2f}) — 获利能力极其强劲。注：若交易笔数较少（如<{total_trades if total_trades < 20 else 20}笔），需谨防小样本特征偏差。")
        
    if current_losing_streak > 0 and not is_circuit_broken:
        risk_advice.append(f"⚠️ **连亏警报**: 当前处于 {current_losing_streak} 连亏中，请关注风控限额。")
        
    return rule_text, risk_advice


def fetch_ai_report(df: pd.DataFrame, total_trades: int, win_rate: float, total_pnl: float, total_fee: float, 
                     wl_ratio: float, pf: float, max_dd: float, sharpe: float) -> str:
    """
    AI 智能诊断
    """
    api_key = os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return ""
        
    api_url = os.environ.get("AI_API_URL", "https://api.openai.com/v1/chat/completions")
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")
    
    recent_summary = df[['datetime', 'side', 'pnl', 'text']].tail(10).to_string()
    
    prompt = f"""
    你是一个高水平的量化交易策略分析师。下面是某个自动化交易机器人在 Gate.io 的实盘交易数据评估指标。
    
    评估指标:
    - 交易笔数: {total_trades} 笔
    - 胜率: {win_rate*100:.2f}%
    - 累计净盈亏 (已扣除手续费): {total_pnl:.2f} USDT
    - 手续费总额: {total_fee:.2f} USDT
    - 盈亏比 (平均盈/平均亏): {wl_ratio if (wl_ratio != float('inf') and not np.isinf(wl_ratio)) else 'N/A'}
    - 获利因子 (Profit Factor): {pf if (pf != float('inf') and not np.isinf(pf)) else 'N/A'}
    - 最大回撤: {max_dd*100:.2f}%
    - 估算夏普比率: {sharpe:.2f}
    
    最近10笔交易历史:
    {recent_summary}
    
    请结合上述真实实盘数据，生成一份简明直击痛点的诊断报告：
    1. 指出当前策略表现的优缺点；
    2. 评估当前手续费摩擦、胜率与盈亏比的搭配是否合理健康；
    3. 给出现在行情下的风控或参数调优建议。
    字数限制 350 字以内，语气要客观、简练、专业。
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
            print(f"⚠️ AI 接口返回异常 status={resp.status_code}: {resp.text}")
            return f"AI 分析暂时不可用 (API 返回错误 {resp.status_code})"
    except Exception as e:
        print(f"⚠️ 无法获取 AI 分析: {str(e)}")
        return f"AI 分析暂时不可用 (连接异常)"


def main():
    api_key = os.environ.get("GATE_API_KEY")
    api_secret = os.environ.get("GATE_API_SECRET")
    
    if not api_key or not api_secret:
        print("❌ 错误: 缺少 GATE_API_KEY 或 GATE_API_SECRET 环境变量！")
        sys.exit(1)
        
    symbol, days = get_report_config()
    print("=" * 60)
    print(f"🚀 开始生成策略评估报告...")
    print(f"📌 交易对合约: {symbol}")
    print(f"📅 评估天数范围: {days} 天")
    print("=" * 60)
    
    client = GateClient(api_key, api_secret)
    
    end_dt = datetime.datetime.now(datetime.timezone.utc)
    start_dt = end_dt - datetime.timedelta(days=days)
    
    df = fetch_all_position_closes(client, symbol, start_dt, end_dt)
    
    try:
        acct = client.get_account()
        current_equity = acct.get('total', 1000.0)
    except Exception as e:
        print(f"⚠️ 无法获取当前账户本金，默认使用 1000.0 U: {e}")
        current_equity = 1000.0
        
    report_dict = calculate_metrics_to_json(df, symbol, days, start_dt, end_dt, current_equity)
    
    template_path = os.path.join(os.path.dirname(__file__), "templates", "report_template.html")
    if not os.path.exists(template_path):
        print(f"❌ 错误: 找不到模板文件 {template_path}，请确认其是否存在！")
        sys.exit(1)
        
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    report_json_str = json.dumps(report_dict, ensure_ascii=False)
    output_html_content = html_content.replace("__REPORT_DATA_PLACEHOLDER__", report_json_str)
    
    start_date_str = start_dt.strftime("%Y%m%d")
    end_date_str = end_dt.strftime("%Y%m%d")
    report_filename = f"report_{symbol.lower()}_{start_date_str}_to_{end_date_str}.html"
    
    report_filepath = os.path.join(os.path.dirname(__file__), report_filename)
    with open(report_filepath, "w", encoding="utf-8") as f:
        f.write(output_html_content)
        
    print(f"✅ HTML 报告已成功渲染并保存为: {report_filepath}")
    
    pnl_sign = "+" if report_dict['total_pnl'] >= 0 else ""
    pf_str = f"{report_dict['profit_factor']:.2f}" if report_dict['profit_factor'] is not None else "∞"
    
    streak_warning = ""
    if report_dict['current_losing_streak'] >= 3:
        streak_warning = "🔴 连亏熔断触发！请检查系统！"
    elif report_dict['current_losing_streak'] > 0:
        streak_warning = f"⚠️ {report_dict['current_losing_streak']} 连亏中"
        
    diagnostic_summary = "策略运行中，摩擦损耗在预算内。"
    if report_dict['current_losing_streak'] >= 3:
        diagnostic_summary = "🚨 警告：已触发连亏熔断阈值，系统已被叫停，请核实持仓！"
    elif report_dict['avg_slippage_ticks'] > 15.0:
        diagnostic_summary = f"⚠️ 警告：当前滑点税高达 {report_dict['avg_slippage_ticks']:.1f} Ticks，损耗严重，建议降低敞口。"
    elif report_dict['profit_factor'] is not None and report_dict['profit_factor'] < 1.15 and report_dict['total_trades'] > 10:
        diagnostic_summary = "💀 获利因子跌破生死线，实盘数学期望值为负，建议立即停机复盘。"
    elif report_dict['current_losing_streak'] > 0:
        diagnostic_summary = f"⚠️ 连亏次数逼近熔断红线，请密切关注下一单执行情况。"
        
    caption = f"""📊 *[实盘战报]* \- {symbol}
⏱ *统计周期*：自 {start_dt.strftime('%m-%d')} 至 {end_dt.strftime('%m-%d')} ({days} 天)

💰 *【盈亏速览】*
• 累计净利： *{pnl_sign}{report_dict['total_pnl']:.2f} U* (已扣手续费/资金费)
• 获利因子： *{pf_str}* (健康阀值 > 1.15)
• 胜率笔数： *{report_dict['win_rate']*100:.1f}%* (赢: {report_dict['win_count']} | 输: {report_dict['loss_count']})

🛡️ *【风控水位】*
• 连亏计数： *{streak_warning if streak_warning else '🟢 无连亏'}*
• 最大连亏： *{report_dict['max_losing_streak']}* 连亏
• 水下深度： *{report_dict['current_drawdown']:.2f} U* (({report_dict['current_drawdown_pct']*100:.1f}%))

⚙️ *【摩擦异常】*
• 平均滑点： *{report_dict['avg_slippage_u']:.2f} U* / 单 (约 *{report_dict['avg_slippage_ticks']:.1f} Ticks*)
• 资金费率： *{report_dict['total_funding_fee']:.2f} U*
• 摩擦损耗比： *{report_dict['friction_ratio']*100:.1f}%*

👮‍♂️ *【风控官诊断】*
_{diagnostic_summary}_

💡 _请点击下方 HTML 文件在浏览器中打开，查看完整交互图表与风控审计细则。_"""

    html_caption = f"""📊 <b>[Gate.io 实盘战报] - {symbol}</b>
⏱ <b>统计周期</b>：自 {start_dt.strftime('%m-%d')} 至 {end_dt.strftime('%m-%d')} ({days} 天)

💰 <b>【盈亏速览】</b>
• 累计净利： <b>{pnl_sign}{report_dict['total_pnl']:.2f} U</b> (已扣手续费/资金费)
• 获利因子： <b>{pf_str}</b> (健康阀值 &gt; 1.15)
• 胜率笔数： <b>{report_dict['win_rate']*100:.1f}%</b> (赢: {report_dict['win_count']} | 输: {report_dict['loss_count']})

🛡️ <b>【风控水位】</b>
• 连亏计数： <b>{streak_warning if streak_warning else '🟢 无连亏'}</b>
• 最大连亏： <b>{report_dict['max_losing_streak']}</b> 连亏
• 水下深度： <b>{report_dict['current_drawdown']:.2f} U</b> ({report_dict['current_drawdown_pct']*100:.1f}%)

⚙️ <b>【摩擦异常】</b>
• 平均滑点： <b>{report_dict['avg_slippage_u']:.2f} U</b> / 单 (约 <b>{report_dict['avg_slippage_ticks']:.1f} Ticks</b>)
• 资金费率： <b>{report_dict['total_funding_fee']:.2f} U</b>
• 摩擦损耗比： <b>{report_dict['friction_ratio']*100:.1f}%</b>

👮‍♂️ <b>【风控官诊断】</b>
<i>{diagnostic_summary}</i>

💡 <i>请点击下方 HTML 文件在浏览器中打开，查看完整交互图表与风控审计细则。</i>"""

    success = send_telegram_document(report_filepath, caption=html_caption)
    if success:
        print("📱 报告文件已成功推送至 Telegram！")
    else:
        print("❌ 警告: 报告文件推送至 Telegram 失败！")
        
    print("🎉 报告工作流执行完毕。")


if __name__ == "__main__":
    main()
