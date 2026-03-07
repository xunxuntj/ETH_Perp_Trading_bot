# Stop Loss Order Modification - API Research Notes

## Problem Statement
用户通过Gate.io UI能够修改触发单的trigger_price，**保持订单ID和create_time不变**。
例子：订单ID `2030304634127515648`，从3000 → 2999 → 2998，ID始终未变。

## Current Implementation
当前代码使用**cancel+create方案**：
- 取消现有订单 (DELETE /api/v4/futures/usdt/price_orders/{order_id})
- 创建新订单，保留所有参数除了trigger_price (POST /api/v4/futures/usdt/price_orders)
- **结果**：触发价格正确更新，但订单ID会改变

### Code Location
- [gate_client.py](gate_client.py) - `update_price_order()` method (line ~457)
- [trading_executor.py](trading_executor.py) - `adjust_stop_loss()` method (line ~320)

## API Endpoint Investigation

### Tested Endpoints (All Failed)
```
❌ PUT    /api/v4/futures/usdt/price_orders/{order_id}
   - Body: {"trigger": {"price": "2994"}}
   - Error: 400 "Invalid param:order_id" 或 "Invalid param:trigger price"
   
❌ PATCH  /api/v4/futures/usdt/price_orders/{order_id}
   - Error: 405 Method Not Allowed
   
❌ POST   /api/v4/futures/usdt/price_orders/{order_id}
   - Error: 405 Method Not Allowed
```

### Successfully Working Endpoints
```
✅ GET    /api/v4/futures/usdt/price_orders?contract=ETH_USDT&status=open
✅ POST   /api/v4/futures/usdt/price_orders (create new order)
✅ DELETE /api/v4/futures/usdt/price_orders/{order_id} (cancel order)
```

## Possible Solutions

### Option 1: WebSocket API
Gate.io可能提供WebSocket API用于实时订单修改，而REST API暂不支持。
- 需要研究Gate.io官方WebSocket文档
- 订单修改可能通过WebSocket实现：`/ws/v4/futures/usdt`

### Option 2: Hidden REST Endpoint
可能存在其他REST端点用于修改：
- `/api/v4/futures/usdt/price_orders/{order_id}/amend` (未验证)
- `/api/v4/futures/usdt/price_orders/{order_id}/update` (未验证)
- 或需要特定的HttpHeader或版本号

### Option 3: 修改订单的其他字段
也许不是通过修改单独的trigger_price，而是通过：
- 修改trigger对象的所有字段(包括strategy_type等)
- 使用不同的request body格式
- 需要在body中包含order_id以外的识别信息

### Option 4: 权限/特定条件
- 订单必须处于特定状态（但查询显示都是"open"）
- 需要特定的API权限设置
- 需要特定的签名方式

## User's Method - To Investigate

请提供以下信息以帮助调查：

### ❓ 问题1: 你是通过什么方式修改的？
- [ ] Gate.io网页版交易界面
- [ ] Gate.io移动应用
- [ ] Python API库 (可否分享代码?)
- [ ] curl/HTTP客户端 (可否分享命令?)
- [ ] 其他 (请说明)

### ❓ 问题2: 能否提供浏览器网络请求日志？
- 打开Gate.io网页版
- 按F12打开开发者工具 → Network标签
- 修改一次stop loss order
- 查看发送的HTTP请求详情（URL、Method、Headers、Body）
- 分享相关信息

### ❓ 问题3: Order ID是否真的完全不变？
- 修改前：ID=`2030304634127515648`, create_time=`1772897320`
- 修改后：ID是否仍为`2030304634127515648`?
- create_time是否仍为`1772897320`?

## Next Steps

1. **获取用户的网络请求信息**后，分析API调用格式
2. **查阅Gate.io官方API文档**的最新版本中关于price_orders修改的说明
3. **尝试WebSocket API**如果存在
4. 根据发现更新`gate_client.py`的`update_price_order()`方法

## Related Documentation
- Gate.io Futures API: https://www.gate.io/api/docs/delivery/index.html
- WebSocket连接相关(如果使用): `/ws/v4/futures/usdt`

---
**Last Updated**: 2026-03-07 15:40 UTC
**Current Status**: cancel+create方案可用，寻求true in-place修改方案
