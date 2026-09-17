# 使用本机模型聊天

AI Baby 默认使用 `mock`：无需模型、无需 API key，也不访问网络。想使用本机模型时，先自行启动已经安装好模型的本地服务，再显式运行设置向导。AI Baby 不会安装服务、下载或拉取模型，也不会扫描其它端口。

## 最短路径：选择已有 Ollama 模型

安装了 AI Baby 命令后运行：

```sh
ai-baby --setup-local
```

直接从源码运行时，在仓库目录打开终端：

```powershell
# Windows PowerShell
.\start.cmd --setup-local
```

```sh
# macOS / Linux
sh start.sh --setup-local
```

向导默认查询 `http://127.0.0.1:11434/api/tags`，列出服务报告的模型名称、大小和修改时间。它只查询模型元数据，不发送宝宝档案、聊天或记忆。列表出现后输入编号，或输入 `q` 取消；选择完成后，在同一进程里使用该模型开始聊天。

向导还会询问是否保存连接配置：回车只用于本次；输入 `y` 会在宝宝数据目录创建新的 `local-model-时间戳.json`，并显示下次启动的完整命令。文件只含版本、provider、地址和模型名，不含 API key，不修改 `.env`，也不会覆盖同名文件。

**保存的 JSON 不会自动加载。** 下次需显式传入 `--local-config`，并继续使用同一个宝宝数据目录，例如：

```sh
ai-baby --local-config "你的配置文件.json" --data-dir "你的宝宝数据目录"
```

从源码运行时，把命令开头的 `ai-baby` 换成 `.\start.cmd`（PowerShell）或 `sh start.sh`。连接配置不会迁移或复制宝宝数据库；切换模型不会清空记忆，`--data-dir` 决定使用哪个宝宝。未传入保存文件时，仍按原来的环境变量 / `.env` 配置启动，未配置 provider 则使用 `mock`。

只想查看列表，可以运行下面的命令。它查询后退出，不打开宝宝数据库：

```sh
ai-baby --local-models
```

## 使用其它本机 OpenAI-compatible 服务

`local-openai` 支持通过 `GET <base_url>/models` 选择服务提供的模型，再通过 `POST <base_url>/chat/completions` 聊天。例如，本机服务使用端口 1234：

```sh
ai-baby --setup-local --local-provider local-openai --local-url http://127.0.0.1:1234/v1
```

同样的 `--local-provider` 和 `--local-url` 参数也适用于 `--local-models`；它们仅用于这两个发现命令。`local-openai` 未指定地址时默认使用 `http://127.0.0.1:8080/v1`。请以自己服务实际监听的端口为准。

| 服务 | AI Baby 预设 | 地址示例 | 协议依据 |
| --- | --- | --- | --- |
| Ollama | `ollama` | `http://127.0.0.1:11434/v1` | [模型列表](https://docs.ollama.com/api/tags)、[OpenAI 兼容接口](https://docs.ollama.com/api/openai-compatibility) |
| llama.cpp 的 llama-server | `local-openai` | `http://127.0.0.1:8080/v1` | [官方 server 文档](https://github.com/ggml-org/llama.cpp/tree/master/tools/server) |
| vLLM | `local-openai` | `http://127.0.0.1:8000/v1` | [官方 OpenAI-compatible server 文档](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/) |
| LM Studio | `local-openai` | `http://127.0.0.1:1234/v1` | [官方兼容接口文档](https://lmstudio.ai/docs/developer/openai-compat) |

这些服务提供相关协议接口，表格不代表每个版本、模型或部署组合都已实际验证。本项目自动测试使用本机 fake HTTP server，覆盖列表解析、选择、请求格式及失败恢复；没有安装这些服务或运行真实模型来评测生成质量。模型需要支持聊天请求；列表中的可选条目本身不能证明它适合中文、能理解宝宝角色，或能在当前硬件上及时生成回复。

Ollama 发现地址只接受根路径或 `/v1`，然后固定查询同一服务的 `/api/tags`；选择模型后统一使用 `/v1` 作为聊天前缀。通用 `local-openai` 会保留自定义路径前缀并追加 `/models`。两种列表都最多接受 100 条、1 MiB 响应；重复名称、异常字段或超限列表会被拒绝。

## 手动配置与需要认证的服务

已有 `.env` 配置继续有效。例如手动指定本机服务及已知模型 ID：

```dotenv
AI_BABY_PROVIDER=local-openai
AI_BABY_BASE_URL=http://127.0.0.1:8080/v1
AI_BABY_MODEL=填写服务实际提供的模型ID
```

使用 Ollama 时将 provider 改为 `ollama`；不设置地址则使用其默认端口 11434。两个本机预设都不需要 `AI_BABY_ALLOW_EXTERNAL=true`，也不需要 dummy key。

本机模式默认不发送 `Authorization`，即使其它用途的 `AI_BABY_API_KEY` 仍留在环境中。只有需要认证的本机聊天服务，才手动同时设置 `AI_BABY_ALLOW_LOCAL_AUTH=true` 和 `AI_BABY_API_KEY`。全局 `OPENAI_API_KEY` 始终不会被读取。

**发现列表始终不带认证，向导启动的聊天也不带认证。** 如果服务保护了 `/models`，请手动配置已知模型 ID 和认证；向导不会自动尝试密钥。保存的 JSON 不保存密钥或认证开关，显式重载时聊天认证仍由上述环境配置决定。

## 本机连接的隐私边界

两个本机预设只允许 `localhost`、`127.0.0.1` 和 IPv6 的 `[::1]`，拒绝公网地址和局域网地址。连接绕过系统 / 环境代理，直接使用数值回环 socket；`localhost` 不经 DNS 解析，支持 IPv4 和 IPv6。重定向一律拒绝，HTTPS 继续验证证书。URL 不能带用户名、密码、查询串或片段。

选择模型后，聊天会将当前输入、资料、检索到的记忆和近期聊天发送给指定的本机服务。AI Baby 的连接目标是本机，**但无法约束这个服务是否再转发到云端、写日志或加载工具**。请求中的 `store=false` 也不能代替服务自身的隐私设置。AI Baby 不向模型授予数据库、文件或工具权限，模型输出不会直接成为数据库指令。

Ollama 本机 API 可以代理云模型，参见[官方认证说明](https://docs.ollama.com/api/authentication)。发现结果如果含非空 `remote_model` 或 `remote_host`，向导会标记该条目并阻止选择；不会根据模型名称猜测是否远程。元数据由服务提供，缺少标记不构成离线证明，手动配置的模型也不会额外触发列表检查。

若需要 Ollama 仅在本地运行，可由你为 **Ollama 服务进程** 设置 `OLLAMA_NO_CLOUD=1`，然后重启该服务；设置在 AI Baby 进程中不会改变已经运行的 Ollama。具体配置方式见 [Ollama 官方 FAQ](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features)。AI Baby 不会替你修改这些服务设置。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 检测不到本地服务 | 确认服务已经启动，并核对类型、地址和端口；程序不会替你启动或安装。 |
| 列表为空 | 在服务中检查本机已有模型；AI Baby 不会执行下载或 `pull`。 |
| 只显示远程模型 | 向导不能选用它们；先在服务中准备可用的本地模型并核对云功能设置。 |
| 模型列表格式错误 / 401 / 404 | 检查是否使用正确预设、`/v1` 路径及认证设置；受保护的列表需改为手动配置。 |
| 列表正常，聊天超时或退回离线回答 | 检查模型是否支持聊天、是否加载成功及硬件资源。发现超时固定为 3 秒；聊天默认总时限为 30 秒，可用 `AI_BABY_TIMEOUT` 设置为 1–120 秒。 |
| 重启后又是原来的模式 | 保存连接文件不等于自动启用；使用向导显示的 `--local-config` 启动命令。 |
| 看到新出生流程 | 核对启动时打印的数据目录；使用原来的 `--data-dir`，不要重建或替换数据库。 |

网络失败时，本轮可退回 `MockProvider` 的基础离线回答，正常完成的学习和角色状态仍按原有事务规则保存。等待生成时不持有 SQLite 写事务；`Ctrl+C` 可取消等待。基础离线回答没有真实模型的开放式语言能力，也不代表模型已经恢复。人格、关系和情绪一直都是软件模拟状态。

其它数据隐私、备份和遗忘边界见 [README](../README.md) 与 [SECURITY](../SECURITY.md)。
