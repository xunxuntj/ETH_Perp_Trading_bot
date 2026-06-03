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

# 载入项目配置中的实盘 SYMBOL
try:
    from config import SYMBOL as DEFAULT_SYMBOL
except ImportError:
    DEFAULT_SYMBOL = "SOL_USDT"


def calculate_default_days() -> int:
    """
    计算从 2026年6月2日 到当前日期的实际天数
    如果结果小于等于 0，则默认返回 1 天
    """
    # 统一使用 UTC 时区计算
    base_date = datetime.datetime(2026, 6, 2, tzinfo=datetime.timezone.utc)
    current_date = datetime.datetime.now(datetime.timezone.utc)
    
    # 将时间截断到天以精确计算相差天数
    base_day = datetime.datetime(base_date.year, base_date.month, base_date.day, tzinfo=datetime.timezone.utc)
    current_day = datetime.datetime(current_date.year, current_date.month, current_date.day, tzinfo=datetime.timezone.utc)
    
    diff_days = (current_day - base_day).days
    return max(1, diff_days)


def get_report_config():
    """
    从环境变量中提取报告配置参数，并处理默认值
    """
    # 1. 交易对 symbol 优先取环境变量 REPORT_SYMBOL
    symbol = os.environ.get("REPORT_SYMBOL")
    if not symbol or symbol.strip() == "":
        symbol = DEFAULT_SYMBOL
    symbol = symbol.strip().upper()
        
    # 2. 天数 days 优先取环境变量 REPORT_DAYS
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
    
    max_pages = 50  # 限制翻页上限，防止死循环
    page = 0
    
    print(f"🔍 启动分页获取 {contract} 平仓记录...")
    print(f"📅 查询时间区间: {start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} ~ {end_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # 记录上一轮的时间戳，作为死循环的安全防线
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
                t = int(item.get('time', 0))
                if t < min_time_in_page:
                    min_time_in_page = t
                
                # 剔除早于我们设定起始时间的数据
                if t < start_timestamp:
                    continue
                    
                page_closes.append({
                    'time': t,
                    'datetime': datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    'side': item.get('side', ''),  # long 或 short
                    'pnl': float(item.get('pnl', 0)),  # 净盈亏 (含手续费)
                    'pnl_pnl': float(item.get('pnl_pnl', 0)),  # 仓位盈亏 (不含手续费)
                    'pnl_fee': float(item.get('pnl_fee', 0)),  # 手续费 (负数)
                    'text': item.get('text', ''),  # 备注/版本
                    'entry_price': float(item.get('long_price', 0) or item.get('short_price', 0) or 0),
                })
            
            if not page_closes:
                break
                
            all_closes.extend(page_closes)
            
            # 翻页逻辑：向前移 1 秒
            if min_time_in_page >= to_timestamp:
                to_timestamp -= 1
            else:
                to_timestamp = min_time_in_page - 1
                
            # 🚨 终极安全阀：保证 to_timestamp 必须严格递减，拒绝任何可能的边界情况死循环
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
    # 按时间升序排序
    df = df.sort_values('time').reset_index(drop=True)
    return df


def calculate_metrics_to_json(df: pd.DataFrame, symbol: str, days: int, start_dt: datetime.datetime, end_dt: datetime.datetime) -> dict:
    """
    计算评估指标并格式化为前端可直接渲染的字典
    """
    if df.empty:
        # 空数据时返回空结构
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
            "trades": []
        }
        
    total_trades = len(df)
    profitable_trades = df[df['pnl'] > 0]
    losing_trades = df[df['pnl'] <= 0]
    
    win_count = len(profitable_trades)
    loss_count = len(losing_trades)
    
    win_rate = win_count / total_trades if total_trades > 0 else 0
    
    avg_win = profitable_trades['pnl'].mean() if win_count > 0 else 0
    avg_loss = abs(losing_trades['pnl'].mean()) if loss_count > 0 else 0
    
    # 获利因子
    total_gains = profitable_trades['pnl'].sum()
    total_losses = abs(losing_trades['pnl'].sum())
    profit_factor = total_gains / total_losses if total_losses > 0 else (float('inf') if total_gains > 0 else 0)
    
    # 盈亏比
    ratio_avg_win_loss = avg_win / avg_loss if avg_loss > 0 else (float('inf') if avg_win > 0 else 0)
    
    total_pnl = df['pnl'].sum()
    total_fee = df['pnl_fee'].sum()
    
    # 最大回撤计算 (假设 1000U 虚拟本金)
    initial_capital = 1000.0
    cum_pnl = df['pnl'].cumsum()
    capital_curve = initial_capital + cum_pnl
    running_max = capital_curve.cummax()
    drawdown = (capital_curve - running_max) / running_max
    max_dd = drawdown.min()
    
    # 夏普比率估算
    trades_returns = df['pnl'] / initial_capital
    std_return = trades_returns.std()
    sharpe = (trades_returns.mean() / std_return * np.sqrt(total_trades)) if std_return > 0 and total_trades > 1 else 0
    
    # 多空次数统计 (注意 side: long 表示平多仓(卖出)，short 表示平空仓(买入))
    # 为清晰起见，我们将平仓方向翻译为建仓时的多/空方向：
    # 平仓 side='long' (卖出) 说明开仓是多头(Long)；side='short' (买入) 说明开仓是空头(Short)。
    long_count = len(df[df['side'] == 'long'])
    short_count = len(df[df['side'] == 'short'])
    
    # 绘制折线图的 label 和数据
    chart_labels = df['datetime'].tolist()
    # 图表数据：从0开始累计
    chart_data = [0] + cum_pnl.tolist()
    # 补齐 label，首位加上 "开始" 占位
    chart_labels = ["开始"] + chart_labels
    
    # 生成规则引擎评估
    rule_analysis, risk_advice = generate_rules_report(total_pnl, win_rate, ratio_avg_win_loss, max_dd, total_fee, avg_win)
    
    # 大模型 AI 评估 (可选)
    ai_analysis = fetch_ai_report(df, total_trades, win_rate, total_pnl, total_fee, ratio_avg_win_loss, profit_factor, max_dd, sharpe)
    
    # 转换明细列表格式
    trades_list = []
    for _, row in df.iterrows():
        trades_list.append({
            "datetime": row['datetime'],
            "side": row['side'],
            "pnl": row['pnl_pnl'],  # 仓位盈亏
            "fee": row['pnl_fee'],  # 手续费
            "net_pnl": row['pnl'],  # 净盈亏
            "entry_price": row['entry_price'],
            "text": row['text']
        })
        
    # 对 Infinity 值处理以防 JSON 解析失败
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
        "trades": trades_list[::-1]  # 倒序排列，最新交易在最上面展示
    }


def generate_rules_report(total_pnl: float, win_rate: float, wl_ratio: float, max_dd: float, total_fee: float, avg_win: float):
    """
    根据核心指标计算生成规则报告
    """
    win_rate_pct = win_rate * 100
    max_dd_pct = abs(max_dd * 100)
    
    # 总体表现
    if total_pnl > 0:
        rule_text = f"🟢 **总体表现**: 策略在评估期内实现**盈利 (+{total_pnl:.2f} USDT)**。 "
    else:
        rule_text = f"🔴 **总体表现**: 策略在评估期内处于**亏损 ({total_pnl:.2f} USDT)**。 "
        
    # 策略风格判断
    if win_rate_pct > 55 and wl_ratio < 1.2:
        rule_text += "该策略当前表现出**高胜率、中低盈亏比**的特征，通常属于短线波段或网格类风格。此风格应重点提防黑天鹅行情导致的单次大额亏损抹去前期利润。"
    elif win_rate_pct < 45 and wl_ratio > 1.8:
        rule_text += "该策略表现为**低胜率、高盈亏比**的特征，为典型的**趋势跟踪策略**风格（符合 ADX + SuperTrend 组合）。其核心是‘轻微试错，大浪吃饱’。震荡期会有连续的小幅摩擦止损，属于策略运行的正常成本。"
    else:
        rule_text += "该策略目前表现为**混合平衡型风格**，胜率与盈亏比相对均衡。"
        
    # 风控建议列表
    risk_advice = []
    
    if max_dd_pct > 15:
        risk_advice.append(f"⚠️ **回撤预警**: 最大回撤达到了 **{max_dd_pct:.2f}%**，回撤偏大。请检查单笔风险敞口，建议调低 `RISK_FIXED_AMOUNT` 或 `RISK_PERCENT` 以降低本金损耗。")
    else:
        risk_advice.append(f"✅ **回撤控制**: 最大回撤控制在 **{max_dd_pct:.2f}%**，处于健康风控区间。")
        
    if abs(total_fee) > abs(total_pnl) and total_pnl > 0:
        risk_advice.append(f"⚠️ **手续费磨损过重**: 总手续费高达 **{abs(total_fee):.2f} USDT**，已超过您的净利润。这通常是频繁开平仓导致的摩擦损耗，建议提高 ADX 过滤阈值或切换至更大周期以降低交易频次。")
    else:
        risk_advice.append(f"✅ **手续费占比**: 手续费共计 **{abs(total_fee):.2f} USDT**，损耗在合理预算范围内。")
        
    return rule_text, risk_advice


def fetch_ai_report(df: pd.DataFrame, total_trades: int, win_rate: float, total_pnl: float, total_fee: float, 
                     wl_ratio: float, pf: float, max_dd: float, sharpe: float) -> str:
    """
    向大模型（如 OpenAI 兼容接口）获取智能评估报告（如果配置了相关的 API 密钥）
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
    # 1. 验证 Gate API 凭证
    api_key = os.environ.get("GATE_API_KEY")
    api_secret = os.environ.get("GATE_API_SECRET")
    
    if not api_key or not api_secret:
        print("❌ 错误: 缺少 GATE_API_KEY 或 GATE_API_SECRET 环境变量！")
        sys.exit(1)
        
    # 2. 载入参数配置
    symbol, days = get_report_config()
    print("=" * 60)
    print(f"🚀 开始生成策略评估报告...")
    print(f"📌 交易对合约: {symbol}")
    print(f"📅 评估天数范围: {days} 天")
    print("=" * 60)
    
    # 3. 初始化 Gate 客户端并抓取数据
    client = GateClient(api_key, api_secret)
    
    end_dt = datetime.datetime.now(datetime.timezone.utc)
    start_dt = end_dt - datetime.timedelta(days=days)
    
    df = fetch_all_position_closes(client, symbol, start_dt, end_dt)
    
    # 4. 计算指标
    report_dict = calculate_metrics_to_json(df, symbol, days, start_dt, end_dt)
    
    # 5. 替换模板文件
    template_path = os.path.join(os.path.dirname(__file__), "templates", "report_template.html")
    if not os.path.exists(template_path):
        print(f"❌ 错误: 找不到模板文件 {template_path}，请确认其是否存在！")
        sys.exit(1)
        
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    # 将打包好的字典序列化为 JSON 字符串
    report_json_str = json.dumps(report_dict, ensure_ascii=False)
    
    # 进行占位符替换
    output_html_content = html_content.replace("__REPORT_DATA_PLACEHOLDER__", report_json_str)
    
    # 6. 保存报告文件
    start_date_str = start_dt.strftime("%Y%m%d")
    end_date_str = end_dt.strftime("%Y%m%d")
    report_filename = f"report_{symbol.lower()}_{start_date_str}_to_{end_date_str}.html"
    
    report_filepath = os.path.join(os.path.dirname(__file__), report_filename)
    with open(report_filepath, "w", encoding="utf-8") as f:
        f.write(output_html_content)
        
    print(f"✅ HTML 报告已成功渲染并保存为: {report_filepath}")
    
    # 7. 通过 Telegram 发送文档
    caption = f"📊 交易策略评估报告\n\n📌 标的: {symbol}\n📅 周期: {days} 天 ({start_dt.strftime('%Y-%m-%d')} 至 {end_dt.strftime('%Y-%m-%d')})\n📈 净收益: {report_dict['total_pnl']:.2f} USDT\n🗂️ 总交易笔数: {report_dict['total_trades']} 笔\n\n💡 请点击下方 HTML 文件在浏览器中打开以查看完整交互图表与智能分析报告。"
    
    success = send_telegram_document(report_filepath, caption=caption)
    if success:
        print("📱 报告文件已成功推送至 Telegram！")
    else:
        print("❌ 警告: 报告文件推送至 Telegram 失败！")
        
    # 8. 清理临时文件 (在 Action 执行中我们会保留或者自动销毁，但这里我们可以在控制台提示)
    print("🎉 报告工作流执行完毕。")


if __name__ == "__main__":
    main()
