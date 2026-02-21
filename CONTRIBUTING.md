# 🤝 贡献指南

感谢您对 ETH SuperTrend Trading Bot 项目的兴趣！本文档说明如何为项目做出贡献。

## 📌 项目愿景

建立一个**高质量、可靠、易用**的开源 ETH 交易策略框架，使交易者能够：
- 快速理解和验证交易策略
- 安全地部署到生产环境
- 根据需求灵活定制
- 与社区分享经验和改进

## 🎯 我们欢迎的贡献类型

### 1. 📚 文档改进

**最容易的贡献方式！无需编码**

- 改进现有文档的清晰性
- 添加更多使用示例
- 修复文档中的错误或过时信息
- 翻译文档到其他语言
- 添加常见问题 Q&A

**如何开始**:
```bash
1. Fork 本仓库
2. 编辑相关 .md 文件
3. 提交 Pull Request
4. 我们会很快审核并合并
```

**示例**: 
- "为 CONFIGURATION.md 添加日文翻译"
- "改进 DEPLOYMENT.md 中 VPS 部分的操作步骤"
- "在 QUICK_START.md 添加常见问题"

### 2. 🐛 Bug 修复

**需要编码但流程明确**

- 修复 API 调用问题
- 修复指标计算错误
- 改进错误处理
- 修复兼容性问题

**如何开始**:
```bash
1. 创建 Issue 描述问题
2. 本地重现问题
3. 编写测试用例验证修复
4. 提交 Pull Request
5. 等待审核和合并
```

**标准**:
- 提交前确保所有测试通过
- 添加回归测试防止再次发生
- 更新相关文档

### 3. ✨ 功能改进

**需要设计和编码**

- 优化现有算法性能
- 改进用户体验
- 添加新的通知渠道（Discord, Email)
- 支持新交易对
- 改进风险管理逻辑

**如何开始**:
```bash
1. 在 Issue 中讨论你的想法
2. 等待社区反馈
3. 提交 RFC（设计文档
4. 实现并提交 PR
5. 参与代码审核
```

**示例**:
- "支持 BTC 交易对"
- "添加 Discord 通知"
- "实现机器学习参数优化"

### 4. 🧪 测试改进

**帮助提高代码质量**

- 添加更多单元测试
- 改进集成测试
- 添加压力测试
- 提高测试覆盖率

**如何开始**:
```bash
1. 查看 tests/ 目录下的现有测试
2. 添加新的测试用例
3. 确保测试通过
4. 提交 Pull Request
```

## 🚀 特别需要帮助的领域

这些是我们最迫切需要社区贡献的领域：

### 🌍 国际化 (i18n)

- [ ] 中文文档完善
- [ ] 英文文档校正
- [ ] 添加更多语言支持（日文、韩文、西班牙文）
- [ ] 代码注释多语言化

### 📊 策略优化

- [ ] 回测系统开发
- [ ] 参数优化算法
- [ ] 新的指标库集成
- [ ] 机器学习模型

### 🖥️ 用户界面

- [ ] Web 仪表板（Flask/Django)
- [ ] Desktop GUI（PyQt/Tkinter）
- [ ] 实时监控系统
- [ ] 数据可视化

### 🔧 基础设施

- [ ] Docker 镜像优化
- [ ] Kubernetes 部署支持
- [ ] 数据库支持（持久化）
- [ ] 监控和告警系统

### 📱 通知渠道

- [ ] Discord 集成
- [ ] Slack 集成
- [ ] Email 通知
- [ ] SMS 短信

---

## 📋 贡献流程

### Step 1: Fork 并 Clone

```bash
# 在 GitHub 网页上 Fork 本仓库

# Clone 到本地
git clone https://github.com/YOUR_USERNAME/eth-trading-bot.git
cd eth-trading-bot

# 添加上游远程
git remote add upstream https://github.com/xunxuntj/eth-trading-bot.git
```

### Step 2: 创建特性分支

```bash
# 更新本地 main 分支
git fetch upstream
git checkout main
git merge upstream/main

# 创建特性分支（使用描述性名称）
git checkout -b feature/add-discord-notification
# 或
git checkout -b fix/api-timeout-issue
# 或
git checkout -b docs/improve-deployment-guide
```

### Step 3: 做出更改

```bash
# 编辑文件并测试
# ...

# 查看更改
git status

# 添加更改
git add .

# 提交更改（使用清晰的提交信息）
git commit -m "Add Discord notification support

- Implement Discord webhook integration
- Add configuration for Discord channel ID
- Update NOTIFICATION configuration
- Add tests for Discord notification
- Update documentation"
```

### Step 4: 提交 Pull Request

```bash
# 推送到你的 fork
git push origin feature/add-discord-notification

# 在 GitHub 网页上创建 Pull Request
# - 选择 upstream 的 main 分支为目标
# - 描述你的更改
# - 关联相关的 Issue
```

### Step 5: 代码审核

- 我们会在 1-3 天内审核你的 PR
- 可能会要求修改
- 通过审核后会合并到 main 分支

---

## 💡 贡献最佳实践

### 提交 Issue

**好的 Issue 示例**:
```
标题: DEMA 计算在 ETH_USDT 出现异常值

描述:
当交易对为 ETH_USDT 时，获取 1000 根 1h K线后，
DEMA 值有时会出现 0 或 NaN。

复现步骤:
1. 运行 python main.py
2. 当看到 "获取 K线" 时观察输出
3. 有时会看到 DEMA: 0

预期:
DEMA 应该是非零的有效数值

环境:
- Python 3.11
- pandas 2.0.3
- Gate.io API

附加信息:
- 错误日志: [粘贴日志]
- 时间戳: 2026-02-21 10:30:00 UTC
```

### 提交 Pull Request

**好的 PR 说明**:
```
## 描述
修复 DEMA 计算中的 NaN 问题

## 原因
当 K线数据不完整时，pandas 操作会产生 NaN

## 解决方案
添加数据验证和 NaN 检测

## 更改内容
- [ ] 修复 indicators.py 中的 DEMA 计算
- [ ] 添加单元测试
- [ ] 更新文档

## 测试
- [x] 运行了所有单元测试：通过
- [x] 进行了集成测试：通过
- [x] 在本地验证了修复：通过

## 关联 Issue
Closes #123
```

### 代码风格

遵循 PEP 8 标准：

```python
# ✅ 好的代码
def calculate_supertrend(data: pd.DataFrame, period: int, multiplier: float) -> dict:
    """
    计算 SuperTrend 指标
    
    Args:
        data: K线数据 DataFrame
        period: 计算周期
        multiplier: ATR 倍数
    
    Returns:
        包含 ST 上轨/下轨/方向的字典
    """
    # 代码实现...
    return result

# ❌ 不好的代码
def calcST(d, p, m):  # 变量名不清晰
    # 代码...
    return x  # 没有文档字符串
```

### 测试覆盖

添加的代码必须有测试：

```python
# 在 tests/test_your_feature.py 中
import pytest
from your_module import your_function

def test_your_function_normal_case():
    """测试正常情况"""
    result = your_function(input_data)
    assert result == expected_output

def test_your_function_edge_case():
    """测试边界情况"""
    with pytest.raises(ValueError):
        your_function(invalid_data)

# 运行测试
# pytest tests/test_your_feature.py -v
```

### 文档更新

如果修改了功能，要更新相关文档：

```bash
# 如果修改了配置
- 更新 CONFIGURATION.md

# 如果修改了部署
- 更新 DEPLOYMENT.md

# 如果修改了策略逻辑
- 更新 SIGNAL_LOGIC_QUICK_REFERENCE.md
- 更新 STOPLOSS_TIGHTENING_MECHANISM.md

# 如果修改了架构
- 更新 SYSTEM_ARCHITECTURE.md
```

---

## 📞 获取帮助

### 遇到问题？

1. **查看现有文档** - 可能已有解答
   - [FAQ](SIGNAL_LOGIC_QUICK_REFERENCE.md#常见问题排查)
   - [故障排查](DEPLOYMENT.md#故障排查)

2. **搜索已有 Issue** - 可能有人遇到过
   - https://github.com/xunxuntj/eth-trading-bot/issues

3. **创建新 Issue**
   - 描述问题的详细信息
   - 附加相关日志和错误消息
   - 说明你的环境（Python 版本、OS 等）

4. **联系维护者**
   - 在 Issue 中 @mention 维护者
   - 或发送邮件给 maintainer

### 讨论想法？

- 创建 Issue 标记为 `discussion`
- 在 GitHub Discussions 中讨论
- 参考现有的 RFC 和设计讨论

---

## 🎁 贡献者奖励

我们感谢所有贡献者！

### 你会获得

1. **致谢** - 在 README.md 中被提及
2. **认可** - GitHub 贡献者徽章
3. **权限** - 活跃贡献者可获得代码审核权限
4. **社群** - 加入我们的开发者社群

### 贡献者等级

| 等级 | 标准 | 权限 |
|------|------|------|
| 贡献者 (Contributor) | 1 次合并的 PR | GitHub 贡献者徽章 |
| 核心贡献者 (Core) | 10+ 次合并的 PR | 代码审核权、Issue 管理权 |
| 维护者 (Maintainer) | 20+ 次合并的 PR | 写入权、发布权 |

---

## 📜 许可证

通过贡献代码，你同意你的贡献将在 MIT 许可证下发布。

---

## 🙏 感谢

感谢每一位贡献者的付出！正是因为有你们，这个项目才能不断完善和进步。

**特别感谢**:
- 所有代码贡献者
- 文档改进者
- 问题报告者
- 测试人员

---

## 联系方式

- 📧 Email: [maintainer email]
- 🐦 Twitter: [@projecthandle]
- 💬 Discussions: GitHub Discussions

---

**欢迎加入我们！🎉**

无论你的技能水平如何，我们都欢迎你的贡献。如果你有任何问题，请随时提问！
