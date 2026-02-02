# 配置指南 - ETH 趋势交易系统

## 必需配置（运行前必须设置）

### Gate.io API
```bash
export GATE_API_KEY="your_api_key"
export GATE_API_SECRET="your_api_secret"
```
**说明**: Gate.io 永续合约 USDT API 密钥，需要启用"USDT 永续合约"权限

### Telegram 通知（可选，但推荐）
```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```
**说明**: 用于接收交易信号、熔断警告等通知；如未设置，消息只打印到控制台

---

## 风险管理配置

### 风险模式选择
```bash
export RISK_MODE="fixed"        # 或 "percent"
```
**可选值**:
- `"fixed"` (默认): 每笔交易风险固定金额
- `"percent"`: 每笔交易风险为账户资产的百分比

### 固定风险模式
```bash
export RISK_FIXED_AMOUNT="10"   # 单笔风险金额 (USDT)
```
**默认值**: `10` USDT  
**说明**: 每笔交易的最大亏损金额。例如 RISK_FIXED_AMOUNT=10 表示止损被击时，最多亏 10 USDT

### 百分比风险模式
```bash
export RISK_PERCENT="0.02"      # 百分比，默认 2%
```
**默认值**: `0.02` (即 2%)  
**说明**: 每笔交易的最大亏损为账户总资产的百分比。例如 RISK_PERCENT=0.02 + 账户 1000U = 每笔风险 20U

### 熔断规则
```bash
# 在 config.py 中修改（无环境变量）
CIRCUIT_BREAKER_EQUITY = 350    # 本金低于此值时停止交易（停手 1 周）
MAX_CONSECUTIVE_LOSSES = 3      # 连续亏损 3 笔时休息 48 小时
```

---

## 交易参数配置

### 杠杆倍数
```bash
# 在 config.py 中修改（无环境变量）
LEVERAGE = 10                    # 10 倍杠杆
```

### 技术指标参数
```bash
# 在 config.py 中修改（无环境变量）
SUPERTREND_PERIOD = 10           # SuperTrend 周期
SUPERTREND_MULTIPLIER = 3.0      # SuperTrend 乘数
DEMA_PERIOD = 200                # DEMA 均线周期
```

### 锁利期 Buffer（保底盈利）
```bash
export LOCK_PROFIT_BUFFER="1"    # 保底盈利金额 (USDT)
```
**默认值**: `1` USDT  
**说明**: 进入锁利期时，固定止损位置，确保至少能赚到这个金额

---

## 调试配置

### 启用 API 调试日志
```bash
export GATE_DEBUG=1              # 打印 Gate.io API 请求/响应日志
export DEBUG=1                   # 打印策略调试信息
```
**说明**: 在 GitHub Action 或本地调试时，输出详细的 API 请求日志和策略计算过程，便于排查问题

---

## 状态文件配置

### 交易状态文件
```bash
export STATE_FILE="trading_state.json"   # 持仓状态文件路径
```
**默认值**: `trading_state.json`  
**说明**: 保存持仓状态、进入时间、阶段等信息，程序重启时恢复状态

---

## GitHub Actions 配置示例

### 完整的 secrets 配置
在 GitHub Repo → Settings → Secrets and variables → Actions 中添加：

```
GATE_API_KEY          = your_api_key
GATE_API_SECRET       = your_api_secret
TELEGRAM_BOT_TOKEN    = your_bot_token
TELEGRAM_CHAT_ID      = your_chat_id
```

### 完整的 workflow 环境变量配置
在 `.github/workflows/*.yml` 中：

```yaml
jobs:
  trade:
    runs-on: ubuntu-latest
    env:
      GATE_API_KEY: ${{ secrets.GATE_API_KEY }}
      GATE_API_SECRET: ${{ secrets.GATE_API_SECRET }}
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      RISK_MODE: "fixed"
      RISK_FIXED_AMOUNT: "10"
      LOCK_PROFIT_BUFFER: "1"
      GATE_DEBUG: "0"    # 生产环境关闭；排查时改为 "1"
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python main.py
      - if: always()
        uses: actions/upload-artifact@v3
        with:
          name: trading-state
          path: trading_state.json
```

---

## 本地调试快速开始

### 1. 基础配置（必需）
```bash
export GATE_API_KEY="your_api_key"
export GATE_API_SECRET="your_api_secret"
```

### 2. 启用调试（可选）
```bash
export GATE_DEBUG=1
export DEBUG=1
```

### 3. 运行 API 测试
```bash
python3 test_gate_api.py $GATE_API_KEY $GATE_API_SECRET ETH_USDT
```

### 4. 运行主程序
```bash
python3 main.py
```

### 5. 运行模拟器测试账户余额解析
```bash
PYTHONPATH=. python3 tests/simulate_gate_client.py
```

---

## 配置说明速查表

| 配置项 | 环境变量 | 默认值 | 说明 |
|------|--------|--------|------|
| Gate.io Key | `GATE_API_KEY` | 无 | ✅ 必需 |
| Gate.io Secret | `GATE_API_SECRET` | 无 | ✅ 必需 |
| Telegram Token | `TELEGRAM_BOT_TOKEN` | 无 | 推荐 |
| Telegram Chat ID | `TELEGRAM_CHAT_ID` | 无 | 推荐 |
| 风险模式 | `RISK_MODE` | `"fixed"` | 固定或百分比 |
| 固定风险 | `RISK_FIXED_AMOUNT` | `10` | USDT |
| 百分比风险 | `RISK_PERCENT` | `0.02` | 2% |
| 锁利 Buffer | `LOCK_PROFIT_BUFFER` | `1` | USDT |
| 状态文件 | `STATE_FILE` | `trading_state.json` | 本地持仓记录 |
| API 调试 | `GATE_DEBUG` | 无 | 启用 Gate API 日志 |
| 策略调试 | `DEBUG` | 无 | 启用策略计算日志 |
| GitHub Summary | `GITHUB_STEP_SUMMARY` | 自动 | GitHub Actions 内自设 |

---

## 常见问题

### Q: 我应该用固定风险还是百分比风险？
**A**: 
- 初学者/本金较小（<1000U）：推荐**固定模式**，例如 `RISK_FIXED_AMOUNT=10`
- 本金较大/想自动扩大风险：推荐**百分比模式**，例如 `RISK_PERCENT=0.02`（2%）

### Q: 如何在 GitHub Actions 中调试"available 为 0"的问题？
**A**: 在 workflow 中添加 `GATE_DEBUG: "1"`，查看 Action 日志输出的 API 响应

### Q: 如何恢复默认配置？
**A**: 删除所有自定义的环境变量，或将 `.env` 文件清空；程序会使用 `config.py` 中的默认值
