# Gate.io API K线数据 - 官方文档核实

**参考文档：** https://www.gate.com/docs/developers/apiv4/zh_CN/#%E5%90%88%E7%BA%A6%E5%B8%82%E5%9C%BA-k-%E7%BA%BF%E5%9B%BE

---

## 📋 关键信息

### API 端点
```
GET /futures/usdt/candlesticks
```

### 参数说明

| 参数 | 类型 | 说明 |
|-----|------|------|
| `contract` | string | 合约名称，如 `ETH_USDT` |
| `interval` | string | K线周期：`1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d` |
| `limit` | integer | 返回的K线数量（最大500条） |
| `from` | integer | 开始时间戳（可选） |
| `to` | integer | 结束时间戳（可选） |

### 返回数据格式

```json
[
  {
    "t": 1234567890,     // K线时间戳（秒）
    "o": "3000.00",      // 开盘价
    "h": "3100.00",      // 最高价
    "l": "2900.00",      // 最低价
    "c": "3050.00",      // 收盘价
    "v": "1000.00",      // 成交量
    "sum": "3050000"     // 成交额
  }
]
```

---

## 🔑 关键理解（基于官方文档）

### ❓ K线完整性问题的答案

根据 Gate.io 官方 API 文档的行为特征：

#### **API返回什么？**
- Gate.io API 在调用时返回的K线数据**包括历史完整的K线**
- **当前进行中的K线**的包含情况取决于K线周期的当前时间

#### **时间戳含义**
K线的时间戳 `t` 代表该K线的**开始时间**：
- 对于 1h K线，时间戳是整点时间（如 12:00）
- 该K线包含 12:00 到 12:59:59 的所有数据

#### **返回的最后一根K线是否完整？**

| 情况 | 说明 |
|-----|------|
| 时间戳在过去 | ✅ 该K线已完成 |
| 时间戳是当前小时/30分钟 | 📊 该K线仍在进行中 |

**例如（现在是 14:35）：**
- 30m K线：最后一根时间戳 = 14:30（已完成）✅
- 1h K线：最后一根时间戳 = 14:00（已完成）✅
- 但如果返回的包括 14:30-15:00 的K线，则那根仍在进行中 📊

---

## 🔧 如何正确使用

### 确认K线完整性的方法

```python
from datetime import datetime, timezone

def is_kline_completed(k_timestamp: int, interval_minutes: int) -> bool:
    """
    判断K线是否已完成
    
    参数：
        k_timestamp: K线时间戳（秒）
        interval_minutes: K线周期（分钟）
    
    返回：
        True: K线已完成
        False: K线进行中
    """
    now = datetime.now(timezone.utc)
    k_time = datetime.fromtimestamp(k_timestamp, tz=timezone.utc)
    
    # 计算该K线应该在多少分钟前完成
    minutes_since_k_start = (now - k_time).total_seconds() / 60
    
    # 如果距K线开始时间 >= K线周期时间，则K线已完成
    return minutes_since_k_start >= interval_minutes
```

### 在代码中的应用

```python
from gate_client import GateClient

client = GateClient(api_key, api_secret)

# 获取30分钟K线
df_30m = client.get_candlesticks("ETH_USDT", "30m", 100)

# 检查最后一根K线是否完整
last_k_timestamp = int(df_30m.index[-1].timestamp())

# 对于30分钟K线
if is_kline_completed(last_k_timestamp, interval_minutes=30):
    print("✅ 最后一根K线已完成")
    last_kline_idx = -1  # 使用 iloc[-1]
else:
    print("📊 最后一根K线仍在进行中")
    last_kline_idx = -2  # 使用 iloc[-2]

# 在strategy.py中使用
last_complete_close = df_30m['close'].iloc[last_kline_idx]
```

---

## 📊 API返回数据顺序

根据官方文档，返回的数据是**按时间升序排列**：

```
[
  {..., "t": 1234567800},  # 最早的K线
  {..., "t": 1234567860},  # 中间
  {..., "t": 1234567920},  # 最近的K线（可能进行中）
]
```

这意味着：
- `df.iloc[0]` = 最早的K线  
- `df.iloc[-1]` = 最新的K线（可能是进行中的）

---

## ✅ 我们代码的验证

### 当前 gate_client.py 实现

```python
def get_candlesticks(self, contract: str, interval: str = "30m", limit: int = 300):
    url = f"{BASE_URL}/futures/usdt/candlesticks"
    params = {
        "contract": contract,
        "interval": interval,
        "limit": limit
    }
    
    resp = self.session.get(url, params=params)
    data = resp.json()
    
    df = pd.DataFrame(data)
    ...
    df = df.sort_values('timestamp').reset_index(drop=True)  # ← 按时间排序
    return df
```

**验证：**
✅ 按时间排序，所以 `iloc[-1]` 确实是最新的数据  
✅ 可能是进行中的K线（需要时间戳检查）  
✅ `iloc[-2]` 是前一根完整K线

---

## 🎯 信号准确性的正确做法

### 推荐方案：使用已完成K线

```python
def get_completed_candlesticks(client, contract, interval, limit=300):
    """
    获取已完成的K线（自动过滤掉进行中的K线）
    """
    df = client.get_candlesticks(contract, interval, limit)
    
    # 获取时间间隔
    intervals = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240, "1d": 1440
    }
    interval_minutes = intervals.get(interval, 60)
    
    # 检查最后一根K线是否完整
    last_k_timestamp = int(df.index[-1].timestamp())
    now = datetime.now(timezone.utc)
    k_time = datetime.fromtimestamp(last_k_timestamp, tz=timezone.utc)
    minutes_since = (now - k_time).total_seconds() / 60
    
    # 如果最后一根K线进行中，返回前面的部分
    if minutes_since < interval_minutes:
        return df[:-1]  # 去掉最后一根（进行中的）
    else:
        return df  # 最后一根已完成，全部返回
```

---

## 📌 应用到我们的项目

### strategy.py 应该使用

```python
# 推荐改进方案
from datetime import datetime, timezone

def analyze(self) -> TradeResult:
    # 获取原始数据
    df_30m_raw = self.client.get_candlesticks(self.contract, "30m", 300)
    df_1h_raw = self.client.get_candlesticks(self.contract, "1h", 300)
    
    # 确保只用已完成的K线
    df_30m = self._ensure_completed_klines(df_30m_raw, 30)
    df_1h = self._ensure_completed_klines(df_1h_raw, 60)
    
    # 现在所有 iloc[-1] 都是已完成的K线
    last_1h_close = df_1h['close'].iloc[-1]  # ✅ 安全
    last_30m_st = st_30m['supertrend'].iloc[-1]  # ✅ 安全

def _ensure_completed_klines(self, df, interval_minutes):
    """确保K线都是已完成的"""
    if len(df) == 0:
        return df
    
    last_k_timestamp = int(df.index[-1].timestamp())
    now = datetime.now(timezone.utc)
    k_time = datetime.fromtimestamp(last_k_timestamp, tz=timezone.utc)
    minutes_since = (now - k_time).total_seconds() / 60
    
    if minutes_since < interval_minutes:
        return df[:-1]  # 去掉进行中的K线
    else:
        return df  # 最后一根已完成
```

---

## 🔍 调试方法

### 如何验证您的部署？

```python
from datetime import datetime, timezone
import pytz

# 获取K线数据
df = client.get_candlesticks("ETH_USDT", "30m", 5)

print("最后3根K线的时间戳：")
for i in range(-3, 0):
    k_time = df.index[i]
    now = datetime.now(timezone.utc)
    minutes_ago = (now - k_time).total_seconds() / 60
    
    status = "📊 进行中" if minutes_ago < 30 else "✅ 已完成"
    print(f"  [{i}] {k_time.strftime('%H:%M')} ({minutes_ago:.1f}分钟前) {status}")
```

**期望输出示例：**
```
最后3根K线的时间戳：
  [-3] 14:00 (65.2分钟前) ✅ 已完成
  [-2] 14:30 (35.1分钟前) ✅ 已完成
  [-1] 15:00 (4.8分钟前) 📊 进行中
```

---

## 🎯 总结

根据官方 Gate.io API 文档：

| 方面 | 结论 |
|-----|------|
| **API返回顺序** | ✅ 按时间升序，最后是最新 |
| **最后一根K线** | ⚠️ 可能是进行中的 |
| **如何判断完整性** | ✅ 比较时间戳与当前时间 |
| **推荐做法** | ✅ 自动过滤进行中的K线 |
| **最安全的方案** | ✅ 确保所有数据都是已完成K线 |

---

## 🔗 相关文件

如果您要应用这个方案到项目，建议：

1. 在 [strategy.py](strategy.py) 中添加 `_ensure_completed_klines()` 方法
2. 在 [analyze()](strategy.py#L176) 中调用此方法
3. 之后所有逻辑都使用 `iloc[-1]` 代表"最新完整K线"
4. 这样就完全解决了之前的"信号源和入场价时序不一致"问题

---

**参考文档完全确认后，我们可以更新项目代码以达到最佳状态！** ✅
