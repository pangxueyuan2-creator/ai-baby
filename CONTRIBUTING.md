# 贡献指南

感谢帮助 AI Baby 成为可理解、可验证的本地成长模拟器。

1. 创建分支，集中解决一个明确问题；较大变更请先说明设计。
2. 使用 Python 3.11+，安装 `pip install -e ".[dev]"`。
3. 尽量先用回归测试复现真实缺陷，再修复；数据库和网络均使用临时 / 本地测试环境，不调用付费 API。
4. 执行 `python -m pytest -q`、`python -m ruff check .`、`python -m ruff format --check .`、`python -m build`。
5. 更新 README 中的行为、数据和隐私说明，提交 PR 并列出验证结果。

保留以下边界：默认无网络、用户明确启用 provider 才能外发、身份不由学到的文本覆盖、每轮一致性事务、数据损坏不静默重置、错误信息不包含聊天或密钥。不要提交真实用户数据库、SQLite 旁文件、备份、导出、API key、`.env` 或对话记录；构建产物、缓存和临时验收报告也不进入提交。

代码使用类型注解、明确模块边界和简短 docstring。新 provider 只生成文本；记忆检索通过 Retriever 接口扩展。**不得在等待 provider 时持有数据库事务**；一轮聊天必须经过预演回滚、无事务生成和 revision 核对提交。不要嵌套 `Baby.chat()` 事务；使用存储层已有的原子写入接口，避免事实和索引部分写入。

schema 变动需要追加迁移注册项，保留已发布迁移原义，并加入冻结的旧版本 SQL fixture、一致性备份、数据保留、失败回滚和中断恢复测试。提交前验证目标 schema / revision / 触发器；不要只更改版本号。fixture 必须是合成数据，不能复制真实 `baby.sqlite3`。

涉及成长、关系、检索或 provider 行为的变更，还应按范围运行：

```sh
python scripts/acceptance_demo.py
python scripts/stress_demo.py --output ../ai-baby-stress-report.json
```

压力脚本默认运行三种养育方式各 1,000 个完整聊天回合，以及 10,000 级事实 / 经历 / 消息，比较人格、关系、成长、日记、相关记忆和 provider context。它还检查单轮变化、饱和、问题频率、查询延迟、遗忘和导出。普通 pytest 包含较短的三宝宝对照；不要用精确硬件延迟或外部生成文本断言跨平台测试。CI 覆盖 Python 3.11–3.14 和 Windows / macOS / Linux，最终报告应区分本地检查与对应 commit 的 Actions 结果。

Provider 回归应使用本地 HTTP 服务验证超时、慢响应头 / 响应体、取消、429、5xx、恶意重定向、格式与大小限制、loopback 代理隔离和并发请求。保持无工具权限、显式 opt-in、`store=false`、脱敏错误与有界重试；不能用真实付费调用替代可复现测试。

项目描述应准确区分离线规则回复、模型生成、模拟状态和真实体验。不要宣称角色拥有意识或生物情绪。
