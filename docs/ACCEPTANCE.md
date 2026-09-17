# 维护验收记录

## 本地模型设置与安全连接（2026-09-17）

初始 main `aaa5a7c51ae36117cc724fafa05ac7f6e1b21b2d`：Windows / Python 3.14 的 pytest 为 **286 passed, 3 skipped**，ruff check 和 wheel/sdist 构建通过；已有 `providers/mock.py` 格式错误使 format 与 [该次 main CI](https://github.com/pangxueyuan2-creator/ai-baby/actions/runs/35201258470) 失败。PR #10 修复后从 `b5a70d8` 开始实现。期间 PR #12 合入 `7e55a7c`，其三个文件再次导致格式检查失败；本轮保留其功能，仅修正布局，并整合时间检索逻辑。

新增 **114 个测试实例**。整合后的完整结果为 **407 passed, 5 skipped（62.72 秒）**；ruff check 通过，format 检查 73 个 Python 文件通过，wheel/sdist 构建通过。Windows 跳过五项 POSIX 权限 / 无符号链接权限检查，其他平台由现有 CI 矩阵执行。没有改变 SQLite schema，仍为 v3；没有修改迁移、重建宝宝或增加运行时依赖。

| 验证 | 已执行的行为 |
| --- | --- |
| 明确发现 | fake Ollama `/api/tags`、通用 `/models`；多个 / 空列表、异常 schema、404、500、拒绝连接、慢响应头、滴流、超大 body、重定向 |
| 网络边界 | DNS 被替换为失败函数仍可连接本机；大小写 HTTP/HTTPS/ALL/NO_PROXY 环境均指向第二 listener，实际连接数为零；GET/POST 的 302/307 不连接重定向目标；IPv6 聊天和 localhost IPv6 回退 |
| 认证与取消 | 本机默认无 Authorization，单独显式 opt-in 后才发送项目 key；发现不发送 key；TLS 握手和响应等待可取消，原 provider 并发 / 重试 / 超时回归继续通过 |
| 上下文 | 八条事实 / 四条经历 / 十二条历史上限，包括新学习和事件补充；虚构的 assistant 月球故事只在非证据 JSON 内，不变成事实或原生 assistant 消息 |
| 模型切换 | mock → A → B → mock 的逻辑数据库快照；实际 fake HTTP 模型选择、失败回退、receipt 重试和重启；资料、名字、事实、经历、人格、成长、关系、日记、候选保留 |
| 配置与 CLI | 必须选择编号；保存需确认、独占创建、不改 `.env`、拒绝覆盖 / 符号链接；不保存 key；`~` 数据目录一致；Ollama 根 URL 自动转为 `/v1`；连续失败提示抑制和恢复提示 |
| 干净安装 | 本地克隆到中文临时路径，用真实 `start.cmd` 出生、设置、保存、重启、换模型、导出与备份；独立 venv 从 wheel 无依赖安装，在源码外启动同一宝宝，全部通过 |

最终 A–H demo 全过：延迟 provider 等待 2 秒，另一个 SQLite writer 在 **10.34 ms** 完成；旧重要事件排名第一。压力脚本重新执行三种养育方式各 **1,000 轮**，最大单轮人格变化为 **0.09**，各 50 条日记且没有重复；并插入 **10,001 facts、10,001 episodes、10,000 messages**：数据库 **11,259,904 bytes**，事实检索中位 **0.253 ms**、经历检索中位 **18.943 ms**，旧重要事件仍排名第一，forget/export/integrity 检查通过。数字为本机测量，不是性能承诺。

全部模型测试只使用临时合成数据和 fake loopback 服务，没有安装 Ollama、下载模型、接触真实用户数据库或调用付费 API。协议兼容测试不证明某个真实模型的角色一致性或中文质量；回环连接也不能限制本机服务继续转发云端。复现入口为下方命令，以及 `tests/test_local_*.py` 和 `tests/test_model_switching.py`。最终跨平台结果请绑定对应 PR/head 的 [Actions](https://github.com/pangxueyuan2-creator/ai-baby/actions) 查看。

### 合并后 macOS 端口测试修正

PR #13 的九项检查均成功，但相同代码合并后的 [macOS / Python 3.11 复验](https://github.com/pangxueyuan2-creator/ai-baby/actions/runs/35205561564/job/105150352701) 暴露一个测试假设：绑定但不监听的端口不保证在三秒期限前立即拒绝 TCP 连接，该次实际返回了安全的 `timeout`。测试改为验证不可用端口会在原期限内以 `transport` 或 `timeout` 失败；新增从 socket 注入明确 `ConnectionRefusedError` 的独立测试，严格检查真实传输链返回 `transport`、目标正确且不泄露异常细节。已有慢响应的严格 timeout 测试保留。没有增加等待时间、跳过测试、修改 provider 行为或重复重跑碰运气；此修正使本轮累计新增测试实例为 115。

修正后完整本地套件为 **408 passed, 5 skipped（61.11 秒）**，共 413 个测试实例；ruff check、73 文件 format check、wheel/sdist build 均通过。运行时代码未变，前述模型切换、干净安装、A–H 与压力结果仍对应相同应用实现。

## 历史：0.3 深度维护验收

本轮基于 `a500a76b6a7fb5f93749bd6a21ccb302c061af32`，没有重建仓库。测试只使用虚构资料、临时数据库、mock 或回环 HTTP，不读取默认宝宝目录或调用付费 API。

## 修改前 baseline

Windows / Python 3.14.5 / SQLite 3.50.4：`117 passed in 32.24s`。开发环境最初缺少 ruff/build；安装项目声明的 `.[dev]` 后，ruff、42 个文件的 format check、wheel/sdist build 全部通过。该 main 的 [GitHub Actions](https://github.com/pangxueyuan2-creator/ai-baby/actions/runs/35191892534) 成功。历史 `65ffb21` 曾在旧 SQLite 上迁移失败，`a500a76` 已修复；本轮不修改已发布的 v2 迁移。

## 发现与修复

没有发现已证实的 Critical 问题。严重性表示对本项目持久数据的影响，不是 CVSS。

| 严重程度 | 根因 | 修复及回归证据 |
| --- | --- | --- |
| High | 独立 learn/episode 多条 SQL 自动提交，索引失败留下半条记忆 | 保存点原子化；故障注入验证事实、索引、revision 同时回滚 |
| High | 嵌套 BEGIN 失败误回滚外层；备份自身活动事务可能卡住 | 入口拒绝，保留外层工作；备份调用先检查事务 |
| High | forget 删除 receipt，旧重试重新学习被忘事实 | v3 撤销标记清空答复，保留窗口内去重身份并拒绝重放 |
| High | 大小写/空白变体绕过 forget；旧经历/curiosity/export 泄漏 | 规范化清理，加重启、导出与 context 测试 |
| High | 候选 ID 重用或同轮已失效仍提示确认 | 持久单调序号、迁移保留最大 ID、只提示仍有效候选 |
| High | 新朋友覆盖旧朋友，纠正后派生经历仍有效 | 多值关系；纠正时停用关联经历/问题；v3 修复已有旧关联 |
| High | 疑问/转述/否定/复合句被当事实、攻击或喜爱 | 保守分句和有限明确纠正规则，不做模糊个人信息推断 |
| High | 慢速滴流永占 worker，并发准入竞态 | 取消活动 socket、原子准入、显式关闭 HTTPError |
| High | localhost 继承系统代理，私人上下文可能外发 | 回环地址禁用代理，使用本地 HTTP 合约回归 |
| High | 通用“我们/第一次”词导致错误共同回忆 | 先提取话题再检索，有实际重叠才用于回忆；缺证据明确说明 |
| High | 迁移提交后才校验并发元数据，启动失败但版本已变 | 改为 COMMIT 前校验；真实进程中断、损坏 schema 与回滚测试 |
| Medium | 关系常量增长快速刷满 | 递减增益、可恢复，保留原有人格渐变公式 |
| Medium | 日记整段截断丢失事件和人格；空记录重复 | 分别限长事件，保留变化摘要，空白区间只更新游标 |
| Medium | 显式自由文字知识没进入成长指标 | world/knowledge 共用知识和 novelty 统计，个人记忆仍分开 |
| Medium | 成熟追问虚构过去课程、普通回复无条件提问 | 仅连接实际证据，减少绕过 curiosity 的追问 |
| Medium | 新数据库/备份/导出 POSIX 权限可能过宽 | 独占 0600 创建；Windows 继承 ACL；不改既有权限 |
| Low | 宝宝名字不显示、非法 ID 回显 Python 异常 | 持久名字用于标签/问候，ID 错误使用明确中文说明 |

## 重复运行

```sh
python scripts/acceptance_demo.py
python scripts/stress_demo.py --turns 1000 --records 10000
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m build
```

本轮 A–H 全通过，现在 A 会迁移至 schema 3；B 第二写入 **6.97 ms**，provider 等待 2 秒；D 旧事件排名 1，查询 **3.86 ms**。CLI subprocess 实际覆盖出生、妈妈称呼、教学、闲聊、调侃、退出/重启/回忆、用户改名/称呼、宝宝改名、personality、journal、forget、export、backup。隔离安装 wheel 后，在源码外重复出生、教学和重启；console 和 module entrypoint 均通过。

## 三种养育方式，各 1,000 轮

相同初始人格和关系，运行完整 preview/generate/commit，模拟每轮间隔 60 秒。

| 结果 | A 温柔探索教学 | B 谨慎保持距离 | C 玩笑游戏教学 |
| --- | ---: | ---: | ---: |
| confidence | 86.11 | 50.00 | 55.66 |
| curiosity | 91.68 | 70.05 | 84.21 |
| caution | 50.00 | 84.95 | 50.00 |
| playfulness | 50.00 | 50.00 | 91.06 |
| trust | 93.46 | 20.00 | 72.30 |
| world knowledge | 200 | 0 | 200 |
| stage | mature | newborn | mature |
| 日记 / 重复 | 50 / 0 | 50 / 0 | 50 / 0 |
| 主动问题数 | 100 | 0 | 100 |
| 数据库字节 | 1,540,096 | 229,376 | 1,122,304 |

最大人格单轮变化 **0.09**，人格/关系没有数值到达 0 或 100。问题间隔至少八轮，最多三个 pending。测试比较全部人格、关系、成长指标、日记、相关事实/经历和真实 provider context，重启后一致。前/后 100 轮耗时中位数：A **9.60/18.83 ms**，B **8.82/8.96 ms**，C **9.35/13.25 ms**。这是当前机器测量，不是性能承诺。CI 运行较短的 120×3 模拟；完整 3,000 轮单独执行。

## 万条长期记忆

插入 **10,001 facts、10,001 episodes、10,000 messages**，消息只保留最近 100 条。数据库 **11,182,080 bytes**，插入 **2.127 s**。事实检索中位 **0.174 ms**；旧重要事件 **18.465 ms** 且排名第一；高频通用词的事实+经历查询组合 **73.184 ms**。查询计划确认使用 `fact_tokens` covering index；forget/export/上下文大小/SQLite 完整性均通过。未引入语义依赖或没有依据的微优化。

## 迁移与验证范围

新增 v2→v3，保留原 v1→v2。冻结 v2 SQL fixture 验证 profile、facts、episodes、growth、relationship、emotion、personality、journals、candidates、curiosity、settings、messages、索引及迁移前备份。子进程 `os._exit` 测试迁移与生成期间突然中断。

原八个 Python 3.11–3.14 / Windows、Linux、macOS 组合保留；quality job 新增源码外干净 wheel 安装和 console entrypoint 验证。最终结果以对应提交的 [Actions](https://github.com/pangxueyuan2-creator/ai-baby/actions) 为准。Windows 对 POSIX 权限及缺失符号链接权限的案例明确 skip，Linux/macOS 执行对应检查。

保留的技术债：词法检索与有限中文语法；外部模型幻觉不受 prompt 绝对保证；仅聊天可能长期 newborn；receipt 只有 256 条窗口；升级前已删除的候选历史未知；遗忘不是语义抹除或安全擦除；DNS 无法强制终止，TLS 握手仍受 socket timeout。没有启用 WAL，现有短事务在本轮测量中已满足双实例场景，不增加无证据的旁文件与恢复复杂度。未加入 streaming、重型模型依赖或完整时间型记忆。

## 历史第二阶段验收记录

基线是 `c4871b8`：62 个测试通过，GitHub CI 全绿。演示使用虚构的 Alice 和临时数据库，不读取默认宝宝目录、不读取 API key、不调用付费服务。

在源码目录执行：

```sh
python scripts/acceptance_demo.py
```

脚本逐项断言 A–H，输出 JSON；断言失败返回非零退出码。数据库和导出文件都位于临时目录，结束自动清理。延迟 provider 是测试替身，不代表真实服务质量。

| 场景 | 可核验内容 |
| --- | --- |
| A | 用冻结 v1 SQL 创建实际文件；迁移后保留 Alice、female、妈妈、草莓偏好；存在迁移前备份 |
| B | provider 等待 2 秒；另一连接成功写入并记录耗时；旧 turn 因 revision 冲突完整取消 |
| C | 两个同初始状态宝宝分别经历 200 次鼓励探索 / 谨慎互动；输出全部人格维度与最大单次变化 |
| D | 90 天前的重要星星事件在新增 1,200 条经历和 1,200 条事实后仍排名第一；输出查询耗时 |
| E | 明确偏好直接保存，含糊偏好只在确认后保存 |
| F | forget 后重新打开数据库仍不检索目标；JSON 导出只包含允许的角色数据字段 |
| G | 无 key 离线聊天正常 |
| H | 超时 provider 自动离线回复，并验证 SQLite 完整性为 ok |

对应自动化测试进一步覆盖 CLI 命令、幂等请求、提交时磁盘错误、Ctrl+C、HTTP retry/redirect/auth 边界、迁移失败回滚、备份失败及并发迁移。完整报告以最终提交的 Actions 为准。

本地 Windows / Python 3.14 实测（2026-09-17）：A–H 全部通过；B 的第二写入耗时 6.54 ms，模拟 provider 等待 2 秒；C 单轮人格最大变化 0.08，200 轮后鼓励组 confidence 63.70、openness 63.70，谨慎组 confidence 50.00、caution 60.67；D 的旧事件排名第一，单次检索 6.91 ms。此快照是一次测量，不是固定性能指标。

## 已知验证范围

情绪摘录遗忘回归：`python -m pytest tests/test_emotion_forget_privacy.py -q`。
八个虚构数据案例覆盖三种情绪变化不复制输入、有效/已替代长事实的旧摘录清理、
重启后的检索/导出/日记/provider context、不相关结构化事件保留、未知 ID 无操作和
中途 SQLite 错误后的全事务回滚。基线 `a717eda` 上六项失败、两项通过；修复后八项通过。
清理是保守的逻辑遗忘，不保证安全擦除，也不清理既有备份或已导出的文件。

- 统计耗时只是当前运行的证据，不是所有硬件的性能承诺。
- anti-spam 防止重复和编号变体，但不检测任意语义垃圾。
- 不验证真实付费模型的回答质量或角色一致性。
- forget 是检索失效与副本清理，不是安全擦除，也无法清除已有备份或服务商数据。
