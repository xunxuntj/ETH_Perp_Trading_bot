import streamlit as st
import pandas as pd
import numpy as np
import datetime
import plotly.graph_objects as go
import requests
import json
import os
import time

# 引入项目现有的 GateClient
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from gate_client import GateClient
from config import GATE_API_KEY as DEFAULT_KEY, GATE_API_SECRET as DEFAULT_SECRET

# 页面基本配置
st.set_page_config(
    page_title="Gate.io 自动化交易策略评估面板",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义 CSS 样式，提升视觉质感 (美观度提升)
st.markdown("""
<style>
    .reportview-container {
        background: #0e1117;
    }
    .metric-box {
        background-color: #1e222b;
        border-radius: 8px;
        padding: 15px;
        border-left: 5px solid #00cfb4;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 10px;
    }
    .metric-title {
        color: #8a99ad;
        font-size: 0.9rem;
        font-weight: 500;
    }
    .metric-value {
        color: #ffffff;
        font-size: 1.8rem;
        font-weight: 700;
        margin-top: 5px;
    }
    .metric-delta {
        font-size: 0.85rem;
        margin-top: 5px;
    }
    .delta-plus {
        color: #00cfb4;
    }
    .delta-minus {
        color: #ff3e60;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 数据获取函数 -----------------

def fetch_position_closes(client: GateClient, contract: str, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
    """
    自适应分页获取指定时间段内某交易对的所有平仓记录
    """
    all_closes = []
    
    # Gate API 的 limit 最大为 100
    limit = 100
    
    # 将结束时间转为秒级时间戳作为分页起点
    to_timestamp = int(end_dt.timestamp())
    start_timestamp = int(start_dt.timestamp())
    
    # 构造请求头和 URL
    BASE_URL = "https://api.gateio.ws/api/v4"
    url_path = "/api/v4/futures/usdt/position_close"
    full_url = f"{BASE_URL}/futures/usdt/position_close"
    
    max_pages = 20  # 防止死循环，最多获取 2000 条平仓记录
    page = 0
    
    progress_bar = st.progress(0, text="正在从 Gate.io 获取数据...")
    
    while to_timestamp > start_timestamp and page < max_pages:
        page += 1
        query_string = f"contract={contract}&limit={limit}&to={to_timestamp}"
        
        # 签名并请求
        headers = client._sign("GET", url_path, query_string, "")
        params = {"contract": contract, "limit": limit, "to": to_timestamp}
        
        try:
            resp = client.session.get(full_url, params=params, headers=headers)
            if resp.status_code != 200:
                st.error(f"API 请求失败 status={resp.status_code}: {resp.text}")
                break
                
            data = resp.json()
            if not data or not isinstance(data, list):
                break
                
            # 解析数据
            page_closes = []
            min_time_in_page = to_timestamp
            
            for item in data:
                # 确保标的合约名称匹配 (防止 API 返回其他合约数据)
                item_contract = item.get('contract', '')
                if item_contract and item_contract != contract:
                    continue
                
                t = int(item.get('time', 0))
                if t < min_time_in_page:
                    min_time_in_page = t
                
                # 如果超出了我们选定的开始时间，则忽略更早的
                if t < start_timestamp:
                    continue
                    
                # 确定方向：优先读取 API 返回的官方 side 字段，否则使用 long_price 兜底判断
                side = item.get('side', '')
                if not side:
                    side = 'long' if float(item.get('long_price', 0)) > 0 else 'short'
                    
                page_closes.append({
                    'time': t,
                    'datetime': datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc),
                    'side': side,  # long / short (平仓时的方向：平多即卖出，平空即买入)
                    'pnl': float(item.get('pnl', 0)),  # 净盈亏 (含手续费)
                    'pnl_pnl': float(item.get('pnl_pnl', 0)),  # 仓位净盈亏 (未扣手续费)
                    'pnl_fee': float(item.get('pnl_fee', 0)),  # 手续费 (负数)
                    'text': item.get('text', ''),  # 订单备注，通常包含策略版本
                    'entry_price': float(item.get('long_price', 0) or item.get('short_price', 0) or 0),
                    'close_price': float(item.get('price', 0)),
                    'size': float(item.get('accumulated_size', 0)),
                })
            
            if not page_closes:
                break
                
            all_closes.extend(page_closes)
            
            # 分页：将 to_timestamp 设置为当前页中最早的一笔平仓的时间 - 1
            if min_time_in_page >= to_timestamp:
                # 避免死循环
                to_timestamp -= 1
            else:
                to_timestamp = min_time_in_page - 1
                
            # 进度反馈
            progress = min(page / max_pages, 1.0)
            progress_bar.progress(progress, text=f"已加载 {len(all_closes)} 笔平仓记录...")
            
            # 稍微限制频次
            time.sleep(0.1)
            
        except Exception as e:
            st.error(f"获取平仓记录发生异常: {str(e)}")
            break
            
    progress_bar.empty()
    
    if not all_closes:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_closes)
    # 按时间升序排列
    df = df.sort_values('time').reset_index(drop=True)
    return df

# ----------------- 评估指标计算 -----------------

def calculate_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
        
    total_trades = len(df)
    profitable_trades = df[df['pnl'] > 0]
    losing_trades = df[df['pnl'] <= 0]
    
    win_count = len(profitable_trades)
    loss_count = len(losing_trades)
    
    win_rate = win_count / total_trades if total_trades > 0 else 0
    
    avg_win = profitable_trades['pnl'].mean() if win_count > 0 else 0
    avg_loss = abs(losing_trades['pnl'].mean()) if loss_count > 0 else 0
    
    profit_factor = (profitable_trades['pnl'].sum() / abs(losing_trades['pnl'].sum())) if loss_count > 0 and abs(losing_trades['pnl'].sum()) > 0 else float('inf')
    ratio_avg_win_loss = avg_win / avg_loss if avg_loss > 0 else float('inf')
    
    total_pnl = df['pnl'].sum()
    total_fee = df['pnl_fee'].sum()
    
    # 累计收益率计算 (假设一个虚拟本金 1000U 计算)
    initial_capital = 1000.0
    cum_pnl = df['pnl'].cumsum()
    cum_pnl_pct = (cum_pnl / initial_capital) * 100
    
    # 最大回撤计算 (基于累计盈亏)
    capital_curve = initial_capital + cum_pnl
    running_max = capital_curve.cummax()
    drawdown = (capital_curve - running_max) / running_max
    max_dd = drawdown.min()
    
    # 夏普比率估算 (以每笔交易的收益计算)
    trades_returns = df['pnl'] / initial_capital
    mean_return = trades_returns.mean()
    std_return = trades_returns.std()
    sharpe = (mean_return / std_return * np.sqrt(total_trades)) if std_return > 0 and total_trades > 1 else 0
    
    return {
        "total_trades": total_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "total_fee": total_fee,
        "profit_factor": profit_factor,
        "ratio_avg_win_loss": ratio_avg_win_loss,
        "max_drawdown": max_dd,
        "sharpe_ratio": sharpe,
        "max_win": df['pnl'].max(),
        "max_loss": df['pnl'].min(),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }

# ----------------- 数据解释与智能诊断 -----------------

def generate_explanation(metrics: dict, df: pd.DataFrame, api_key: str = "") -> str:
    """
    根据指标生成策略评估报告。
    支持规则分析。如果用户提供了大语言模型 API Key，还可以进行 LLM 级智能分析。
    """
    if not metrics:
        return "暂无有效数据用于生成解释。"
        
    win_rate_pct = metrics['win_rate'] * 100
    total_pnl = metrics['total_pnl']
    profit_factor = metrics['profit_factor']
    ratio_win_loss = metrics['ratio_avg_win_loss']
    max_dd_pct = abs(metrics['max_drawdown'] * 100)
    
    # 1. 基础规则诊断
    rule_analysis = "### 📊 策略评估诊断报告 (规则引擎)\n\n"
    
    # 盈亏性质分析
    if total_pnl > 0:
        rule_analysis += f"🟢 **总体表现**: 策略在评估期内实现**盈利 ({total_pnl:.2f} USDT)**。 "
    else:
        rule_analysis += f"🔴 **总体表现**: 策略在评估期内处于**亏损 ({total_pnl:.2f} USDT)**。 "
        
    # 策略风格识别
    if win_rate_pct > 55 and ratio_win_loss < 1.2:
        rule_analysis += "该策略表现为**高胜率、中低盈亏比**的特征，通常属于震荡网格或高频震荡交易风格。此类策略需警惕单次大额亏损（黑天鹅）抹去前期累计收益。"
    elif win_rate_pct < 45 and ratio_win_loss > 1.8:
        rule_analysis += "该策略表现为**低胜率、高盈亏比**的特征，典型代表为**趋势跟踪策略**（如本项目中的 ADX + SuperTrend 组合）。这类策略的特点是‘输小赢大’，靠少数大趋势吃肥，震荡期会有连续的小幅亏损，属于正常现象。"
    else:
        rule_analysis += "该策略表现为**混合型风格**。胜率与盈亏比相对均衡。"
        
    rule_analysis += "\n\n### 🛡️ 风控与诊断建议\n"
    
    # 诊断回撤
    if max_dd_pct > 15:
        rule_analysis += f"- ⚠️ **回撤预警**: 最大回撤达到了 **{max_dd_pct:.2f}%**，回撤偏大。建议核对当前杠杆配置（当前系统默认为 {df.get('leverage', [10])[0] if 'leverage' in df.columns else 10}x）。在高波动率期间，应考虑调低风险系数或降低 `RISK_FIXED_AMOUNT` / `RISK_PERCENT`。\n"
    else:
        rule_analysis += f"- ✅ **回撤控制**: 最大回撤控制在 **{max_dd_pct:.2f}%**，处于健康水平。\n"
        
    # 诊断手续费
    fee_ratio = abs(metrics['total_fee']) / metrics['avg_win'] if metrics['avg_win'] > 0 else 0
    if abs(metrics['total_fee']) > abs(total_pnl) and total_pnl > 0:
        rule_analysis += f"- ⚠️ **磨损警告**: 手续费总计 **{abs(metrics['total_fee']):.2f} USDT**，已超过您的净利润。策略频繁交易导致手续费损耗过重，建议考虑合并信号，或切换到更长周期（如从 30m 切换到 1h 过滤）。\n"
    else:
        rule_analysis += f"- ✅ **手续费占比**: 手续费共计 **{abs(metrics['total_fee']):.2f} USDT**，损耗在合理区间。\n"
        
    # 诊断获利因子 (Profit Factor)
    pf_val = metrics.get('profit_factor', 0.0)
    pf_str = f"{pf_val:.2f}" if pf_val != float('inf') else "∞"
    if pf_val == float('inf') or np.isinf(pf_val) or np.isnan(pf_val) or pf_val is None:
        rule_analysis += f"- 👑 **获利因子评估**: 卓越/无回撤 (PF: {pf_str}) - 期间无任何亏损笔数。注：若交易笔数极少，需谨防样本偏差。\n"
    elif pf_val < 1.0:
        rule_analysis += f"- 💀 **获利因子评估**: 期望值为负/极差 (PF: {pf_val:.2f}) - 策略总盈利未能覆盖总亏损，系统处于实质亏损状态，建议立即停机复盘优化。\n"
    elif pf_val < 1.25:
        rule_analysis += f"- ⚠️ **获利因子评估**: 边际生存/较差 (PF: {pf_val:.2f}) - 扣除手续费及亏损后利润微薄，回撤抵御能力低，生存状态脆弱。\n"
    elif pf_val < 1.5:
        rule_analysis += f"- 🟡 **获利因子评估**: 合格/基本盈利 (PF: {pf_val:.2f}) - 策略可实现基本盈亏覆盖，但抗震荡行情侵蚀的边际空间较小。\n"
    elif pf_val < 2.0:
        rule_analysis += f"- 🟢 **获利因子评估**: 良好/稳健特征 (PF: {pf_val:.2f}) - 盈利能力良好，收益稳健覆盖风险，具备持续实盘运行基础。\n"
    elif pf_val < 3.0:
        rule_analysis += f"- 🚀 **获利因子评估**: 优秀/高效盈利 (PF: {pf_val:.2f}) - 收益显著优于风险，策略对当前行情具有明显期望优势。\n"
    else:
        rule_analysis += f"- 👑 **获利因子评估**: 卓越/异常表现 (PF: {pf_val:.2f}) - 获利能力极其强劲。注：若交易笔数较少（如<20笔），需谨防小样本特征偏差。\n"
        
    # 诊断版本变化
    if 'text' in df.columns:
        versions = df['text'].unique()
        versions = [v for v in versions if v]
        if len(versions) > 1:
            rule_analysis += f"\n### 🔄 策略版本对比\n在所选时间段内，检测到以下订单备注标签（可能代表策略版本变化）：`{', '.join(versions)}`。您可以查看下方表格，筛选特定标签以评估不同版本在实盘的表现。\n"

    # 2. LLM 智能诊断（如果用户配置了 API 秘钥）
    if api_key:
        st.info("🤖 正在调用大语言模型生成智能策略深度分析...")
        try:
            # 简易调用 DeepSeek 或 OpenAI 兼容接口
            # 用户可以填写自定义的 baseUrl 和 model，这里我们默认使用 OpenAI 标准格式
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            # 准备上下文
            recent_trades_summary = df[['datetime', 'side', 'pnl', 'text']].tail(10).to_string()
            prompt = f"""
            你是一个专业的量化交易策略分析师。下面是某个自动化交易机器人在 Gate.io 的实盘交易数据评估指标。
            
            交易对: {df['side'].count()} 笔交易
            指标数据:
            - 总交易笔数: {metrics['total_trades']} 笔 (多仓盈利次数: {metrics['win_count']}, 空仓/亏损次数: {metrics['loss_count']})
            - 胜率: {win_rate_pct:.2f}%
            - 累计净收益 (扣除手续费): {total_pnl:.2f} USDT
            - 手续费总额: {metrics['total_fee']:.2f} USDT
            - 盈亏比 (平均盈利/平均亏损): {ratio_win_loss:.2f}
            - 获利因子 (Profit Factor): {profit_factor:.2f}
            - 最大回撤: {max_dd_pct:.2f}%
            - 夏普比率 (Sharpe Ratio, 按笔数估算): {metrics['sharpe_ratio']:.2f}
            
            最近10笔交易明细:
            {recent_trades_summary}
            
            请根据这些数据，给出一份专业的评估和改进建议，包含：
            1. 对当前策略的整体优缺点诊断。
            2. 手续费、胜率与盈亏比的健康度评估。
            3. 面对当前行情，参数或杠杆设置的调整建议。
            要求：客观、专业、直击痛点，字数在 400 字以内。
            """
            
            body = {
                "model": "gpt-4o-mini",  # 可以让用户在侧边栏选择
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            }
            
            # 使用 openai 接口进行调用
            resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=20)
            if resp.status_code == 200:
                llm_response = resp.json()['choices'][0]['message']['content']
                return rule_analysis + "\n\n---\n\n### 🤖 AI 智能诊断（高级分析）\n" + llm_response
            else:
                return rule_analysis + f"\n\n> ⚠️ AI 接口调用失败 (Status: {resp.status_code}): {resp.text}"
        except Exception as e:
            return rule_analysis + f"\n\n> ⚠️ AI 接口调用发生异常: {str(e)}"
            
    return rule_analysis


# ----------------- 侧边栏交互区 -----------------

st.sidebar.title("🛠️ 参数配置")

# API Keys 载入
st.sidebar.subheader("🔑 Gate.io API 凭证")
api_key_input = st.sidebar.text_input("GATE_API_KEY", value=DEFAULT_KEY, type="password")
api_secret_input = st.sidebar.text_input("GATE_API_SECRET", value=DEFAULT_SECRET, type="password")

# 交易对与时间段选择
st.sidebar.subheader("📈 评估范围")
symbol = st.sidebar.text_input("合约交易对", value="SOL_USDT", help="例如 ETH_USDT, SOL_USDT, BTC_USDT")

# 快速选取时间段
time_option = st.sidebar.selectbox(
    "快速选择时间段",
    ["最近 7 天", "最近 30 天", "最近 90 天", "自定义范围"]
)

now = datetime.datetime.now()
if time_option == "最近 7 天":
    start_date = now - datetime.timedelta(days=7)
    end_date = now
elif time_option == "最近 30 天":
    start_date = now - datetime.timedelta(days=30)
    end_date = now
elif time_option == "最近 90 天":
    start_date = now - datetime.timedelta(days=90)
    end_date = now
else:
    # 自定义范围
    start_date = st.sidebar.date_input("开始日期", now - datetime.timedelta(days=30))
    end_date = st.sidebar.date_input("结束日期", now)
    # 将 date 转为 datetime 格式
    start_date = datetime.datetime.combine(start_date, datetime.time.min)
    end_date = datetime.datetime.combine(end_date, datetime.time.max)

# 大语言模型诊断配置
st.sidebar.subheader("🤖 智能诊断配置 (可选)")
ai_provider = st.sidebar.selectbox("AI 服务商", ["无", "OpenAI / 兼容接口"])
llm_api_key = ""
if ai_provider != "无":
    llm_api_key = st.sidebar.text_input("API Key", type="password", help="输入 API Key 激活 AI 评估")

# 运行评估按钮
run_eval = st.sidebar.button("🚀 运行评估", use_container_width=True)


# ----------------- 主展示区 -----------------

st.title("📊 Gate.io 自动化交易策略评估系统")
st.markdown("通过平仓记录提取实盘数据，多维度评估交易策略收益、风险与效率。")

# 核心逻辑
if run_eval or 'data_loaded' not in st.session_state:
    if not api_key_input or not api_secret_input:
        st.warning("👉 请在侧边栏中配置您的 Gate.io API 凭证，然后点击「运行评估」开始分析。")
        st.stop()
        
    client = GateClient(api_key_input, api_secret_input)
    
    with st.spinner("正在抓取 Gate.io 平仓数据..."):
        df_data = fetch_position_closes(client, symbol, start_date, end_date)
        
    if df_data.empty:
        st.error(f"❌ 未找到 {symbol} 在指定时间范围内的平仓历史记录，请确认该交易对是否有成交，或者调整时间范围。")
    else:
        st.session_state['df_data'] = df_data
        st.session_state['data_loaded'] = True
        st.session_state['metrics'] = calculate_metrics(df_data)

# 展示结果
if st.session_state.get('data_loaded'):
    df = st.session_state['df_data']
    metrics = st.session_state['metrics']
    
    # 1. 核心 KPI 展示区
    st.subheader("🎯 核心表现指标")
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    # 格式化 PNL
    pnl_val = metrics['total_pnl']
    pnl_class = "delta-plus" if pnl_val >= 0 else "delta-minus"
    pnl_sign = "+" if pnl_val >= 0 else ""
    
    with kpi1:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-title">累计净利润 (扣手续费)</div>
            <div class="metric-value">{pnl_sign}{pnl_val:.2f} U</div>
            <div class="metric-delta {pnl_class}">手续费已扣除: {abs(metrics['total_fee']):.2f} U</div>
        </div>
        """, unsafe_allow_html=True)
        
    with kpi2:
        win_rate_pct = metrics['win_rate'] * 100
        win_class = "delta-plus" if win_rate_pct >= 50 else "delta-minus"
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-title">策略胜率 (Win Rate)</div>
            <div class="metric-value">{win_rate_pct:.1f}%</div>
            <div class="metric-delta {win_class}">总笔数: {metrics['total_trades']} (赢: {metrics['win_count']} | 输: {metrics['loss_count']})</div>
        </div>
        """, unsafe_allow_html=True)
        
    with kpi3:
        pf_val = metrics['profit_factor']
        pf_str = f"{pf_val:.2f}" if pf_val != float('inf') else "∞"
        pf_class = "delta-plus" if pf_val >= 1.5 else "delta-minus" if pf_val < 1.0 else ""
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-title">获利因子 (Profit Factor)</div>
            <div class="metric-value">{pf_str}</div>
            <div class="metric-delta {pf_class}">盈亏比 (Avg W/L): {metrics['ratio_avg_win_loss']:.2f}</div>
        </div>
        """, unsafe_allow_html=True)
        
    with kpi4:
        dd_val = metrics['max_drawdown'] * 100
        dd_class = "delta-plus" if abs(dd_val) < 10 else "delta-minus" if abs(dd_val) > 20 else ""
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-title">最大回撤率 (Max DD)</div>
            <div class="metric-value">{dd_val:.1f}%</div>
            <div class="metric-delta {dd_class}">估算夏普比率: {metrics['sharpe_ratio']:.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    # 2. 收益图表与明细数据
    st.markdown("---")
    chart_col, table_col = st.columns([3, 2])
    
    with chart_col:
        st.subheader("📈 累计盈亏曲线图")
        # 准备图表数据
        df['cum_pnl'] = df['pnl'].cumsum()
        
        fig = go.Figure()
        
        # 绘制主收益曲线
        fig.add_trace(go.Scatter(
            x=df['datetime'],
            y=df['cum_pnl'],
            mode='lines+markers',
            name='累计盈亏 (USDT)',
            line=dict(color='#00cfb4', width=3),
            marker=dict(size=6, symbol='circle'),
            hovertemplate='时间: %{x}<br>累计净盈亏: %{y:.2f} USDT<extra></extra>'
        ))
        
        # 标零基准线
        fig.add_hline(y=0, line_dash="dash", line_color="#8a99ad", line_width=1)
        
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=20, r=20, t=10, b=10),
            xaxis=dict(
                gridcolor='#232733',
                title="交易平仓时间",
                titlefont=dict(color='#8a99ad'),
                tickfont=dict(color='#8a99ad')
            ),
            yaxis=dict(
                gridcolor='#232733',
                title="净利润 (USDT)",
                titlefont=dict(color='#8a99ad'),
                tickfont=dict(color='#8a99ad')
            ),
            legend=dict(font=dict(color='#8a99ad'))
        )
        
        st.plotly_chart(fig, use_container_width=True)

    with table_col:
        st.subheader("💡 交易分布特征")
        
        # 盈亏分布情况表格
        dist_data = {
            "统计指标": [
                "单笔最大盈利", "单笔最大亏损", 
                "平均每笔盈利", "平均每笔亏损", 
                "总出手续费", "每笔交易平均净损益"
            ],
            "数值 (USDT)": [
                f"{metrics['max_win']:.2f}",
                f"{metrics['max_loss']:.2f}",
                f"{metrics['avg_win']:.2f}",
                f"-{metrics['avg_loss']:.2f}",
                f"{metrics['total_fee']:.2f}",
                f"{(metrics['total_pnl']/metrics['total_trades']):.2f}"
            ]
        }
        st.table(pd.DataFrame(dist_data))
        
        # 多空平仓笔数
        if 'side' in df.columns:
            st.markdown("**多空仓平仓类型分布**")
            # 统计平仓方向：long（平多仓，即卖出），short（平空仓，即买入）
            side_counts = df['side'].value_counts()
            st.bar_chart(side_counts)

    # 3. 诊断报告区
    st.markdown("---")
    st.subheader("📝 策略诊断与深度分析报告")
    
    explanation = generate_explanation(metrics, df, llm_api_key)
    st.markdown(explanation)
    
    # 4. 原始平仓数据表格 (可供筛选、导出)
    st.markdown("---")
    st.subheader("🗂️ 平仓交易历史明细")
    
    # 支持备注/版本标签筛选
    if 'text' in df.columns:
        all_tags = ['全部'] + list(df['text'].unique())
        selected_tag = st.selectbox("🎯 按订单备注(策略版本标记)筛选数据", all_tags)
        
        if selected_tag != '全部':
            display_df = df[df['text'] == selected_tag]
        else:
            display_df = df
    else:
        display_df = df
        
    # 重命名列使之更易读
    readable_df = display_df[['datetime', 'side', 'size', 'entry_price', 'close_price', 'pnl_pnl', 'pnl_fee', 'pnl', 'text']].copy()
    readable_df['datetime'] = readable_df['datetime'].dt.strftime('%Y-%m-%d %H:%M')
    readable_df['side'] = readable_df['side'].map({'long': 'Sell (平多)', 'short': 'Buy (平空)'}).fillna(readable_df['side'])
    readable_df['entry_price'] = readable_df['entry_price'].map(lambda x: f"{x:.4f}" if pd.notna(x) else "---")
    readable_df['close_price'] = readable_df['close_price'].map(lambda x: f"{x:.4f}" if pd.notna(x) else "---")
    readable_df.columns = ['平仓时间', '平仓方向', '张数', '建仓均价', '平仓均价', '合约盈亏(U)', '手续费(U)', '净盈亏(U)', '订单备注/版本']
    
    # 对净盈亏列进行高亮
    def highlight_pnl(val):
        color = '#00cfb4' if val > 0 else '#ff3e60' if val < 0 else '#ffffff'
        return f'color: {color}; font-weight: bold;'
        
    st.dataframe(
        readable_df.style.map(highlight_pnl, subset=['净盈亏(U)', '合约盈亏(U)']),
        use_container_width=True
    )
    
    # 导出 CSV
    csv = readable_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 导出筛选后的交易明细 (CSV)",
        data=csv,
        file_name=f"{symbol}_closes_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )
