# 🚀 自动交易快速启动指南

**版本:** V9.6-Exec  
**状态:** ✅ 完全实现

---

## 📌 3 步启动自动交易

### 步骤 1️⃣ : 环境配置（5 分钟）

```bash
# 克隆项目
git clone https://github.com/xunxuntj/ETH_Perp_Trading_bot.git
cd ETH_Perp_Trading_bot

# 安装依赖
pip install -r requirements.txt

# 配置 API 凭证（获取方法见下文）
export GATE_API_KEY="your_gate_api_key"
export GATE_API_SECRET="your_gate_api_secret"
export TELEGRAM_BOT_TOKEN="your_telegram_token"
export TELEGRAM_CHAT_ID="your_telegram_chat_id"

# 配置交易参数
export ENABLE_AUTO_TRADING="false"  # 先用模拟模式
export RISK_FIXED_AMOUNT="10"       # 单笔风险 10U
export CIRCUIT_BREAKER_EQUITY="350" # 保护线
```

### 步骤 2️⃣ : 信号验证（1-2 周）

```bash
# 运行在模拟模式
python main.py

# 预期输出
# 🕐 2026-02-21 23:00:00 UTC
# ⚠️ 模拟（信号）模式
# 📋 策略: open_long
# ✅ 开多信号！
# ...
```

**验证清单:**
- [ ] 信号生成正确（开多/开空/平仓）
- [ ] 止损位置合理
- [ ] Telegram 通知正常
- [ ] 没有异常错误

### 步骤 3️⃣ : 启用自动交易（生产环境）

```bash
# ⚠️ 确保上述验证完成！

# 启用自动交易
export ENABLE_AUTO_TRADING="true"

# 运行
python main.py

# 预期输出
# ✅ 自动交易模式
# ✅ 交易已执行
```

---

## 🔑 获取 API 凭证

### Gate.io API

1. 登录 https://www.gateio.pro
2. 账户 → API 密钥管理
3. 创建新 API 密钥
4. 勾选权限:
   - ✅ 交易（现货、期货）
   - ✅ 查询余额
   - ❌ 提币（安全考虑）
5. 复制 **Key** 和 **Secret**

```bash
export GATE_API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export GATE_API_SECRET="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

### Telegram 通知

1. 在 Telegram 中找到 **@BotFather**
2. 发送 `/newbot` 创建机器人
3. 填入机器人名称、handle
4. 复制得到的 **TOKEN**
5. 将机器人添加到你的群组
6. 在群组中找到 **@userinfobot**，发送任何消息
7. 获取 **Chat ID** (以 `-100` 开头的数字)

```bash
export TELEGRAM_BOT_TOKEN="123456789:ABCDEFGHabcdefgh"
export TELEGRAM_CHAT_ID="-1001234567890"
```

---

## 📊 完整的自动交易流程

```
每 30 分钟执行一次 (通过 GitHub Actions)
    ↓
┌─────────────────────────────────────┐
│ 1. 获取数据                         │
│    - K 线数据 (1H + 30m)           │
│    - 账户信息                       │
│    - 持仓信息                       │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ 2. 计算指标                         │
│    - SuperTrend (ST)                │
│    - DEMA(200)                      │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ 3. 分析信号                         │
│    - 开仓信号、平仓信号            │
│    - 持仓阶段、止损位置            │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ 4. 执行交易 (仅当 ENABLE_AUTO=true) │
│    - 开仓 + 止损                    │
│    - 调整止损                       │
│    - 平仓 + 反手                    │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ 5. 发送通知                         │
│    - Telegram 通知                  │
│    - 日志记录                       │
└─────────────────────────────────────┘
```

---

## ✅ 开仓条件一览

### 📈 **开多条件** (3 重过滤都满足)

```
✅ 1H ST 绿
✅ 1H 收盘价 > DEMA200
✅ 30m ST 绿

执行: 市价开多 → 设置止损 @ 30m ST → 推送通知
```

### 📉 **开空条件** (3 重过滤都满足)

```
✅ 1H ST 红
✅ 1H 收盘价 < DEMA200
✅ 30m ST 红

执行: 市价开空 → 设置止损 @ 30m ST → 推送通知
```

---

## 🛑 平仓条件一览

### **生存期/锁利期** (浮盈 < 1U 或 已锁利)
```
30m ST 变条 → 平仓
```

### **换轨期** (浮盈 ≥ 1U 且 1H ST 更紧)
```
1H ST 变色 → 平仓
```

---

## 📈 持仓管理三阶段

### 🔵 **阶段 1: 生存期** (浮盈 < 1U)
- 止损: 30m ST (动态跟随)
- 离场: 30m ST 变色
- 目标: 渡过早期风险

### 🟡 **阶段 2: 锁利期** (浮盈 ≥ 1U, 1H ST 不够紧)
- 止损: 锁定在 `entry ± 1U/仓位` (不再变动)
- 离场: 30m ST 变色
- 目标: 保底盈利

### 🟣 **阶段 3: 换轨期** (1H ST 比锁利阈值更紧)
- 止损: 1H ST (动态跟随)
- 离场: 1H ST 变色
- 目标: 追求趋势利润

---

## 🔒 风险控制

### 熔断机制
```
账户本金 ≤ 350U → ⛔ 停止交易

作用: 防止账户爆破
可配置: CIRCUIT_BREAKER_EQUITY
```

### 冷静期机制
```
连续亏损 ≥ 3 次 → ⏸️ 停止交易 1 周

作用: 防止过度交易
可配置: MAX_CONSECUTIVE_LOSSES
```

### 风险掌控
```
固定风险额: 10 USDT (可配置)
单笔最大亏损: 10 USDT
百笔止损离场时能保本

作用: 精确控制风险
```

---

## 📝 重要配置参数

| 参数 | 默认值 | 说明 |
|------|-------|------|
| **ENABLE_AUTO_TRADING** | false | 启用自动交易 |
| **RISK_FIXED_AMOUNT** | 10 | 单笔风险 (USDT) |
| **CIRCUIT_BREAKER_EQUITY** | 350 | 熔断线 (USDT) |
| **MAX_CONSECUTIVE_LOSSES** | 3 | 冷静期触发 |
| **LOCK_PROFIT_BUFFER** | 1 | 锁利缓冲 (USDT) |
| **LEVERAGE** | 10 | 杠杆倍数 |

---

## 🚀 GitHub Actions 自动化 (推荐)

### 配置工作流

```yaml
# .github/workflows/trading.yml
name: ETH Auto Trading

on:
  schedule:
    - cron: '*/30 * * * *'  # 每 30 分钟

jobs:
  trade:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: python main.py
        env:
          GATE_API_KEY: ${{ secrets.GATE_API_KEY }}
          GATE_API_SECRET: ${{ secrets.GATE_API_SECRET }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          ENABLE_AUTO_TRADING: 'true'
```

### 设置 Secrets

1. 进入 GitHub repo → Settings → Secrets and variables → Actions
2. 添加:
   - `GATE_API_KEY`
   - `GATE_API_SECRET`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

---

## 🧪 测试命令

### 运行单次分析（不交易）
```bash
export ENABLE_AUTO_TRADING="false"
python main.py
```

### 运行自动交易（仅模拟）
```bash
export ENABLE_AUTO_TRADING="true"
export DRY_RUN="true"
python main.py
```

### 启用调试日志
```bash
export DEBUG="true"
export VERBOSE="true"
python main.py
```

---

## 📊 监控的关键指标

### ✅ 健康检查
- K 线数据是否更新
- 账户余额是否充足
- 持仓是否与预期一致
- 止损单是否已设置

### ⚠️ 预警信号
- 连续亏损接近 3 次
- 账户本金接近 350U
- 止损单异常（未设置或被触发）
- API 调用失败或超时

### 📈 风险指标
- 单笔最大亏损
- 最大连胜/连败
- 整体胜率
- 资金曲线

---

## 🆘 常见问题排查

### 信号没有生成？
```bash
# 1. 检查 API 连接
python -c "from gate_client import GateClient; g = GateClient(API_KEY, API_SECRET); print(g.get_account())"

# 2. 检查 K 线数据
python -c "from gate_client import GateClient; g = GateClient(API_KEY, API_SECRET); print(g.get_candlesticks('ETH_USDT', '1h', 10))"

# 3. 启用调试
export DEBUG=true; python main.py
```

### 交易没有执行？
```bash
# 1. 检查模式
echo $ENABLE_AUTO_TRADING  # 应该是 "true"

# 2. 检查账户余额
python -c "from gate_client import GateClient; print(GateClient(API_KEY, API_SECRET).get_account())"

# 3. 检查持仓限制
python -c "from gate_client import GateClient; print(GateClient(API_KEY, API_SECRET).get_positions('ETH_USDT'))"
```

### 通知没有发送？
```bash
# 1. 检查 Telegram 凭证
curl -X POST https://api.telegram.org/bot{TOKEN}/sendMessage \
  -d chat_id={CHAT_ID} \
  -d text="Test"

# 2. 检查网络连接
ping api.telegram.org
```

---

## 📞 获取帮助

| 问题 | 解决方案 |
|------|---------|
| API 错误 | 检查凭证和账户权限 |
| 网络超时 | 检查连接，重试 |
| 信号错误 | 查看 DEBUG 日志 |
| 交易异常 | 查看执行日志 |
| Telegram 不通 | 检查 Chat ID 格式 |

---

## ✨ 下一步

1. **立即开始:**
   ```bash
   export ENABLE_AUTO_TRADING="false"
   python main.py
   ```

2. **监控 1-2 周:** 验证信号质量

3. **启用自动交易:**
   ```bash
   export ENABLE_AUTO_TRADING="true"
   python main.py
   ```

4. **设置 GitHub Actions:** 自动化执行

5. **定期检查:** 监控日志和性能

---

**祝您交易顺利!** 🎯📈

最后更新: 2026-02-21
