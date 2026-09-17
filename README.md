# AI Baby / AI 宝宝养成模拟器

[![Tests](https://github.com/pangxueyuan2-creator/ai-baby/actions/workflows/ci.yml/badge.svg)](https://github.com/pangxueyuan2-creator/ai-baby/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

一个从“第一次开始运行”诞生、在交流和教学中积累经历的 AI 角色。记忆、身份和成长属于本地程序；自然语言生成可替换。退出程序、重启电脑后，宝宝仍然记得照顾者和学过的内容。

**0.2 工程升级：** 无网络写锁的乐观提交、v1 数据自动备份迁移、个体人格、重要旧经历检索、候选记忆确认、成长日记、适度主动提问，以及 forget/export 命令。原来的出生、称呼和启动方式继续保留。[一轮聊天的数据流与设计](docs/ARCHITECTURE.md)。

**这是 AI 角色 / 成长模拟器，不代表真实意识。情绪、人格、关系、依恋和成长均为软件状态模拟，不是生物意义上的感受。** 宝宝明确知道自己是 AI、不是人类。它不会因你离开而扣分，也不会要求排他性陪伴。

## 快速开始

需要 **Python 3.11 或更新版本**。运行时只使用 Python 标准库，无 API key 也可启动，无需安装数据库服务。

```sh
git clone https://github.com/pangxueyuan2-creator/ai-baby.git
cd ai-baby
```

**Windows：** 双击 `start.cmd`，或在 PowerShell 运行：

```powershell
.\start.cmd
```

**macOS / Linux：**

```sh
sh start.sh
```

这两种方式直接从源码启动，**不需要 pip 下载依赖**。Windows 需要 `python` 在 PATH 中；如弹出 Microsoft Store，请先安装 Python 并勾选 Add Python to PATH。不同终端的 emoji 字体可能不同。

也可安装命令行入口（初次构建可能需要联网下载 setuptools）：

```sh
python -m venv .venv
# Windows
.venv\Scripts\python -m pip install .
.venv\Scripts\python -m ai_baby
# macOS / Linux
.venv/bin/python -m pip install .
.venv/bin/ai-baby
```

已安装包的 Python 环境也支持 `python -m ai_baby`。如果 Windows 应用控制拦截 pip 生成的 `ai-baby.exe`，直接使用上面的模块启动方式，无需修改安全策略。仓库使用 src 布局，未安装时请用启动脚本。

## 第一次出生与重启

下面是终端操作示例。Alice 是虚构测试用户：

```text
==============================
AI Baby / AI 宝宝
==============================
模式：基础离线（无网络请求）
一个新的 AI 宝宝即将出生。它是软件角色，不是真实人类。
你的名字是：
> Alice
请选择性别：1. 男  2. 女  3. 其他 / 不想透露
> 2
AI 宝宝：你好……我好像刚刚开始运行。你叫Alice。
可以叫你“妈妈”吗？回车/可以表示同意，或输入自定义称呼：
> 可以
AI 宝宝：妈妈你好，我是刚出生的 AI 宝宝。我还没有多少经历，你可以慢慢教我吗？
你 > 我喜欢草莓。
AI 宝宝：妈妈，我记住了：用户 · likes · 草莓。
你 > 学习：海豚是一种哺乳动物。
AI 宝宝：妈妈，我记住了：海豚 · 是 · 一种哺乳动物。
你 > /quit
记忆已保存，下次见。

# 再次启动同一个数据目录
AI 宝宝：妈妈，你回来啦。我记得你叫Alice。
你 > 我喜欢什么？
AI 宝宝：你喜欢草莓。
你 > 海豚是什么？
AI 宝宝：你教过我：海豚是一种哺乳动物。
```

男默认“爸爸”、女默认“妈妈”、其他 / 不想透露默认用户名字；任何人都可自定义称呼。回答“不可以”会使用名字。姓名、性别和称呼在出生完成后一起保存。中途 Ctrl+C / EOF 不会生成半份资料。

后续用 `/name 新名字` 和 `/address 新称呼` 修正资料；普通聊天和学到的文本不能覆盖权威身份。可用不同 `--data-dir` 创建独立宝宝：

```powershell
.\start.cmd --data-dir .\data\second-baby
```

```sh
sh start.sh --data-dir ./data/second-baby
```

## 功能与命令

| 功能 | 输入示例 |
| --- | --- |
| 事实 / 世界知识 | `学习：海豚是一种哺乳动物。`、`记住：猫是一种哺乳动物` |
| 自由形式知识笔记 | `记住：遇到问题时先核对资料` |
| 偏好 / 不喜欢 | `我喜欢橘猫。`、`我不喜欢草莓。` |
| 个人信息 | `我住在杭州。`、`我的生日是六月一日。`、`我的职业是设计师。` |
| 简单关系 | `关系：小明是我的朋友`，之后问 `我的朋友是谁？` |
| 重要经历 | `重要事件：今天我们一起学会了一个新词` |
| 查看状态 | `/status` |
| 查看资料 / 修改 | `/profile`、`/name Alex`、`/address 家长` |
| 查看有效事实 | `/memories`，最近 20 条 |
| 查看经历 | `/events`，最近 10 条（含学习和成长事件） |
| 一致性备份 | `/backup` |
| 个体人格 | `/personality` |
| 成长日记 | `/journal`，巩固并查看最近记录 |
| 自然表达 | `其实我从小特别喜欢橘猫。`、`我现在住杭州。`、`我的朋友叫小明。` |
| 候选确认 | `/candidates`、`/confirm ID`、`/reject ID` |
| 记忆控制 | `/forget ID`，先用 `/memories` 找到事实 ID |
| 数据导出 | `/export`，保存到数据目录下的 `exports/` |
| 宝宝名字 | `/baby-name 星芽`，重启后仍保留 |
| 帮助 / 退出 | `/help`、`/quit`（或 `/exit`） |

每轮最多输入 2,000 个字符，单项知识最多 500 字；不接受终端控制字符。可以在一句中用句号分隔多个事实。

### 离线模式的真实边界

`MockProvider` 是**明确标注的规则 / 检索式基础模式，不是本地大语言模型**。它能记忆问答、确认学习、体现身份、问候、回应简单情境和熟人玩笑；未知内容会承认没学过，并提示如何教学。不同成长阶段调整提问表达。它不能进行通用推理，也不能把任意自然语言都正确提取为事实。

整个系统并非一个按关键词输出固定句子的脚本：本地层承担持久化、检索、学习与纠错、关系、成长、事务一致性；provider 只接收动态上下文并生成语言。配置外部 LLM 后才具备模型驱动的自由聊天能力。语言模型的已有知识不等于宝宝的亲身经历；这也不是对模型参数的训练或真正从零培养智能。

## 长期记忆设计

默认保存到：

- Windows：`%USERPROFILE%\.ai-baby\baby.sqlite3`
- macOS / Linux：`~/.ai-baby/baby.sqlite3`
- 可用 `--data-dir` 或 `AI_BABY_DATA_DIR` 覆盖；命令行优先。

启动时自动创建目录。相同目录对应同一个宝宝，与在哪个终端启动无关。相对路径按当前工作目录解析；启动脚本先进入仓库目录。

| 层 | SQLite 表 | 内容 / 保留策略 |
| --- | --- | --- |
| Profile memory | `profile` | 单份权威姓名、性别、称呼、诞生时间 |
| Factual memory | `facts` | 偏好、世界知识、个人信息、关系；记录 `source=user` 和是否有效 |
| Retrieval index | `fact_tokens` | 中文字 / 双字词与英文词索引 |
| Episodic memory | `episodes` | 出生、教学、重要事件、情绪事件、成长里程碑、资料修正 |
| Episode retrieval index | `episode_tokens` | 话题相关度 + importance + 有限近期权重 |
| Relationship / character state | `state` | relationship、emotion、growth、personality、growth_metrics 分开保存 |
| Learning proposals | `candidates` | 最多三条待确认候选，不作为已知事实 |
| Growth journal | `journals` | 有界、确定性的阶段经历和人格变化摘要 |
| Curiosity | `curiosity` | 少量待回答问题和防重复的话题记录 |
| Short-term history | `messages` | 最近 100 条消息，自动清理更早原文 |

事实和经历长期保留；完整聊天原文不是永久归档。数据库没有应用层加密，请使用自己的系统账户、磁盘加密与可靠备份。备份包含完整敏感数据。

### 学习、重复和纠错

- 完全相同的信息经空白 / 大小写 / 末尾标点规范化后去重，不重复增加知识或学习事件。
- “我喜欢草莓”之后“我不喜欢草莓”：相反偏好变为无效，检索只返回当前有效项。再次喜欢可重新激活。
- 相同主语和谓语的世界 / 个人 / 简单关系事实，以新值覆盖当前有效项，旧版本仍保留在库中。例如把“海豚是一种鱼”改为“海豚是一种哺乳动物”。
- 偏好可以有多个对象。MVP 的关系槽位是单值的，例如“我的朋友”；多个同类关系和复杂矛盾消解见路线图。
- 世界知识只表示“用户教过”，未独立核实。问题不会作为事实学习。
- 支持原教学句式和部分明确自然表达，包括“我从小就特别喜欢橘猫”“其实草莓是我最喜欢的水果”“我现在住杭州”“我的朋友叫小明”。未知句式不会自动变成事实，不推断性别、健康信息或身份。
- “我可能喜欢橘猫”会询问确认：只有 `/confirm ID` 后才成为长期事实。候选单独保存在本地，重启可继续确认；`/reject ID` 忽略。查看 `/candidates`，不要把含糊信息当成事实。没有 LLM 自动抽取。

### 检索与上下文预算

`Retriever` 协议允许更换 embedding / 向量检索。当前利用索引在 SQL 中匹配最多 80 个查询词，按词长重叠和主语匹配加分。喜欢 / 不喜欢的概览问题走类别检索。

每次外部请求包含固定 AI 身份、权威资料、发展阶段和个体人格、情绪、关系、最多 **8 条事实、4 条相关经历、12 条最近对话**，以及本轮输入、最多三条明确标注的未确认候选和一条可选追问。历史单条最多 1,200 字，回复最多保存 4,000 字；不是把整个数据库塞进 prompt。这是字符预算而非精确 token 计数。

经历按当前话题的字词匹配、重要度和适度的近期权重综合排序。三个月前的“第一次教我星星”可以在大量后续事件后重新被检索。当前仍是词法检索，不是语义 embedding。资料和记忆作为单独的数据消息，不能修改固定 system 身份。**提示词隔离不是对模型行为的绝对保证**；外部模型仍可能幻觉或偏离角色。provider 接口不提供数据库连接或工具，回复不会执行代码；第三方 Python 插件本身并非沙箱，需要信任其代码。

## 成长模型

阶段：`newborn → baby → child → growing → mature`，表示发展复杂度；`growth.TRAITS` 提供阶段表达指导。**PersonalityState 则表示同一阶段宝宝之间的个体差异**，不会被升级阶段覆盖。

人格有 curiosity、confidence、sociability、caution、playfulness、independence、patience、openness 八项，0–100；初始为 50，好奇心为 70。每轮每项变化不超过 0.20，并在接近边界时衰减。长期鼓励、探索、玩笑、谨慎互动和敌意形成不同倾向。它们都是软件参数，不是意识或生物感受。用 `/personality` 查看。

GrowthMetrics 分开记录世界知识、个人记忆、经历、关系深度、互动类别多样性、活跃时间、重要事件和知识多样性。偏好、个人资料、关系和事件不再混作世界知识。成长分数由以下维度加权：

```text
20 × saturate(互动次数 / 400)
+ 15 × saturate(累计活跃秒数 / 36000)
+ 25 × saturate(有效世界知识的不同 novelty 数 / 100)
+ 10 × saturate(经历记忆数 / 100)
+ 15 × (信任 + 亲近 + 熟悉) / 300
+  5 × saturate(重要事件数 / 30)
+ 10 × min(1, 互动类别数 / 5)

saturate(x) = 1 - exp(-x)
```

各维度收益逐步递减。阶段分数门槛是 0 / 12 / 30 / 52 / 75，并分别要求至少 0 / 10 / 60 / 200 / 500 次互动、0 / 1 / 8 / 25 / 60 种有效世界知识 novelty 和 0 / 1 / 2 / 3 / 4 类互动。完全重复事实不增加学习事件，只有数字 / 标点不同的“词1是值1、词2是值2”共用 novelty。单纯挂机、空聊或编号垃圾不能刷成熟；词法各异的垃圾仍可能绕过启发式，系统不判断世界知识真伪。门槛是可调产品参数，不是心理学年龄测量。

活跃时间使用当前进程的单调时钟，按成功聊天之间的间隔计算，每轮最多计 300 秒；只在成功聊天提交时累计，关闭程序的时间不算。这个时间是参与度近似值，不是精确在线时长。阶段不会因偏好修正、关系变化或知识失效而倒退；实时分数可以下降。

## 关系与模拟情绪

关系包含 `trust`、`attachment`、`familiarity`、`closeness`、`playfulness`，范围 0–100。每轮各值变化最多 0.35，长期互动缓慢累积，退出不会惩罚。

情境分类区分温柔、玩耍、调侃、歧义、真正不友好、用户难过和普通表达。“我很难过”不会降低信任；“这个游戏真糟糕”不会当作对宝宝的攻击。对陌生的“你个笨蛋”会先确认语气；熟悉度 ≥ 20 且信任 ≥ 25 时可轻松回应“又逗我 😼”。明显玩笑标记也有影响，明确敌意优先。

情绪集合为 `calm / happy / curious / sad / playful / nervous / annoyed`。强度按旧值 75% + 目标值 25% 平滑。标签可随情境改变，强度逐渐移动。重要情绪变化写入经历。当前情境分类仍是保守启发式，不等同于可靠的语义情绪分析。

## 可选 LLM 与 API key 配置

默认 `mock` 完全不发网络请求；**仅放入 API key 不会自动启用外部模式**。项目不会读取或复用全局 `OPENAI_API_KEY`。

复制示例配置：

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```sh
# macOS / Linux
cp .env.example .env
```

在本地 `.env` 中填写（不要提交真实 key）：

```dotenv
AI_BABY_PROVIDER=openai-compatible
AI_BABY_ALLOW_EXTERNAL=true
AI_BABY_API_KEY=填写你自己的服务密钥
AI_BABY_BASE_URL=https://api.openai.com/v1
AI_BABY_MODEL=填写服务支持的模型ID
AI_BABY_TIMEOUT=30
AI_BABY_MAX_RETRIES=0
AI_BABY_RETRY_BACKOFF=0.25
```

以上模型和密钥文字只是说明，必须换成有效值。没有写死模型、没有赠送额度，也不保证任意兼容服务支持所有字段。费用和数据政策由提供商决定。

接口实现 `POST {BASE_URL}/chat/completions`，发送 `model`、`messages`、`store=false`，解析 `choices[0].message.content`。参见 [Chat Completions 官方协议](https://developers.openai.com/api/reference/chat-completions/overview)。选择该协议是为满足可替换的 OpenAI-compatible 服务需求；后续可另加 Responses 或本地模型 provider。

外部地址要求 HTTPS；回环 `localhost / 127.0.0.1 / ::1` 允许 HTTP，便于本地兼容服务。本地无鉴权服务可以不填 key（不发送 Authorization），或填写自己的 dummy key。远程服务仍要求 key。URL 不允许内嵌凭据或查询串，禁止跟随 HTTP 重定向。

总等待期限可设置 1–120 秒。默认不重试；可设置最多 2 次重试，仅针对明确 HTTP 429 拒绝，退避最多 2 秒。超时、断连、5xx、认证失败等不自动重试。Ctrl+C 可迅速结束主线程等待和本轮事务；已经送达服务的请求不能撤回，后台传输线程可能等待 socket 超时后结束，其结果不会写入数据库，也不会再安排重试。在它结束前，同一 provider 的后续请求会提示 busy 并离线回复，避免线程不断堆积。暂不支持 streaming。

运行时环境变量覆盖 `.env`；可用 `--env-file 路径` 选择另一份配置。简易 `.env` 解析器支持注释行与 `KEY=value`，不执行 shell、不插值、不支持多行值 / 行尾注释。

认证失败、限流、超时、HTTP 错误、格式异常或超大响应会给出脱敏提示，本轮切回离线回复，已学知识仍然提交。下轮可再次尝试外部服务。错误正文和 API key 不进入日志。

## 隐私与数据恢复

离线模式没有遥测、没有后台上传，所有用户资料、喜好、聊天、长期记忆只在本地。在线模式需主动设置两个开关，并在启动时显示提示：**发送给第三方模型的上下文可能包含用户输入、姓名、性别、称呼、近期聊天及相关记忆。** `store=false` 仅是请求参数，不能替代供应商政策，也不保证第三方不记录数据。

仓库忽略 `.env`、数据库及旁文件、日志、虚拟环境、用户 `data/`。请勿将真实记忆导出到受版本控制的文件，不要在 Issue 中粘贴真实 key、个人资料或完整对话。README 中的测试数据都是虚构示例。

每轮先在短事务中预演本地学习和状态更新并回滚，随后**无数据库事务地等待 provider**，最后核对 revision 并原子提交事实、经历、双方消息和角色状态。等待期间另一实例可以读写；若它改变了状态，旧回复整轮取消，不覆盖新数据、不自动再次调用模型。CLI 会显示冲突说明。磁盘满、Ctrl+C 或异常不会留下半轮学习状态。`Baby.chat(..., turn_id=...)` 支持最近 256 个成功请求的幂等重试，具体边界见架构文档。

### 自动迁移 v1 → v2

第一次用新版打开 v1 数据目录时，程序自动检测 schema version，并先在 `backups/pre-v1-to-v2-时间戳.sqlite3` 创建一致性备份，再在一个事务内增加索引、重要度、人格和辅助表。升级保留旧资料、称呼、事实、经历、关系、情绪、成长阶段和历史；旧 Growth JSON 不被清空。新的 GrowthMetrics 在下一轮成功互动时按真实数据计算。备份失败则不迁移；迁移失败会回滚原始库，不静默重生。成功后 schema version 为 2，旧版程序不应继续打开这个目录；如需降级，请复制迁移前备份到新目录。

### 日记、主动提问和记忆控制

每 20 次成功互动、`/journal` 或正常 `/quit`，会将最多六条近期重要经历及人格变化巩固为一段最多 1,200 字的成长记录。没有新事件但有人格变化时也可记录。完全离线可用，不依赖后台服务；日记不反过来为成长加分，重复查看不会重复写入。所有描述都标注为软件角色状态。

新学到合适内容时，宝宝最早从第六轮开始主动问一个小问题，之后至少相隔八轮。早期问简单例子，成熟阶段问联系与看法变化。最多三条待回答问题；回答以“因为…”或“回答：…”开头会解决最新一条，“不想回答 / 跳过问题”会忽略它，不扣 trust。已问话题保留精简 hash 防重复。这不是完整的自然语言对话管理。

`/forget ID` 让指定事实以及关联 / 匹配经历不再参与检索。为避免旧副本再次唤起内容，同时清空近期对话、缓存回复、待确认候选和全部旧日记；剩余有效经历可再次生成日记。人格和已经达到的阶段不倒退，记忆计数重新计算。**失效记录和已有备份仍在磁盘，这是遗忘检索，不是安全擦除。**

`/export` 生成可读 JSON，包含资料、宝宝名字、全部有效事实、重要经历、成长、关系、情绪、人格和日记。不会导出配置、API key、`.env`、原始聊天、未确认候选或失效事实；使用独占创建，拒绝覆盖。导出本身含私人资料，请勿公开上传。此版本不提供 `/reset`；请使用独立 `--data-dir` 创建另一个宝宝，避免误清空。

运行 `/backup` 将一致性快照保存到 `数据目录/backups/`。恢复方法：

1. 关闭所有使用该数据目录的 AI Baby 进程。
2. 先完整复制当前数据目录（包括可能存在的 SQLite 旁文件），保留原始证据。
3. 创建一个新的空目录，把所选备份复制进去并命名为 `baby.sqlite3`。
4. 使用 `--data-dir 新目录` 启动，核对 `/profile`、`/memories` 和 `/status`。

遇到损坏数据库、损坏状态 JSON 或不支持的新版本数据库，程序显示恢复说明，**不会静默删库重生或覆盖原数据**。MVP 没有自动修复损坏数据库。日志只包含类别级错误，不记录聊天或密钥。

若要彻底删除本地记忆，关闭程序后自行删除该宝宝的数据目录及你保留的备份和导出文件；远端提供商已接收的数据需要依其政策另行处理。本版本不提供单条安全擦除 / 应用层加密功能。

## 项目结构

```text
ai-baby/
├── README.md / LICENSE / CONTRIBUTING.md / SECURITY.md
├── pyproject.toml / .env.example / .gitignore
├── start.cmd / start.sh
├── .github/workflows/ci.yml
├── src/ai_baby/
│   ├── main.py                 # CLI、出生和本地命令
│   ├── baby.py                 # 事务化聊天编排
│   ├── models.py / config.py   # 类型、校验和显式配置
│   ├── memory.py               # SQLite 层、检索、备份
│   ├── learning.py             # 教学与偏好抽取
│   ├── growth.py               # 多维成长和阶段人格
│   ├── relationship.py        # 关系缓慢演化与情境分类
│   ├── emotions.py             # 模拟情绪
│   ├── personality.py          # 长期个体差异
│   ├── candidates.py           # 候选记忆与本地校验
│   ├── journal.py / curiosity.py / management.py
│   ├── migrations/             # 事务迁移与 v1 → v2 备份
│   ├── conversation.py         # 动态上下文 / Retriever 协议
│   └── providers/
│       ├── base.py / mock.py
│       └── openai_compatible.py
├── data/.gitkeep               # 不包含真实用户记忆
└── tests/                      # 单元、进程重启和本地 HTTP 合约测试
```

## 开发与验证

```sh
python -m venv .venv
# 先激活虚拟环境；Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: . .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m build
```

PowerShell 若禁止脚本执行，无需改系统策略：使用 `.venv\Scripts\python` 替代 `python` 即可。

测试使用临时目录和虚构资料，不访问你的宝宝数据库，不调用付费 API。覆盖出生称呼持久化、草莓偏好跨进程重启、海豚知识、熟人玩笑、无 key 启动和 provider 上下文等验收场景，以及事务回滚、并发、损坏、备份、去重、修正、成长、HTTP 异常与隐私预算。

**外部接口测试使用真实本地 HTTP 服务器验证协议，不能等同于真实付费模型的生成质量验证。** CI 用八个测试组合覆盖 Python 3.11 / 3.12 / 3.13 / 3.14，Windows / macOS / Linux：Linux 四个 Python 版本，另两个系统测试 3.11 和 3.14。继续检查 lint、格式与包构建。实际结果见上方 Actions。[可重复的 A–H 验收演示](docs/ACCEPTANCE.md)。

## 扩展与路线图

- 引入可选本地语言模型，实现无需外发数据的自由聊天。
- 将词法 Retriever 换为语义检索，增加精确 token 预算与大库性能优化。
- 更丰富句式、多值关系、候选过期策略和更强的事实冲突管理。
- 增加应用层加密、安全擦除、经过验证的数据导入和后续版本迁移。
- 多语言、本地 Web UI、成长时间线与长期角色一致性评估。
- 测量并调整成长曲线和语气分类；不把拟人参数解释为真实心理状态。

当前版本优先实现可运行、可理解、可扩展的 CLI MVP，没有用空的 UI 或 TODO 替代核心功能。

## 贡献和许可证

欢迎提交小而明确的 PR，先阅读 [贡献指南](CONTRIBUTING.md)。新增 provider 实现 `BaseLLMProvider.generate(context)` 并返回字符串；可恢复的服务错误抛 `ProviderError`，不得直接修改数据库，不得默认外发资料。

项目采用 [MIT License](LICENSE)。安全问题见 [SECURITY.md](SECURITY.md)。
