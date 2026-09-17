# 本地 LLM：Ollama 预设

AI Baby 默认仍使用 `mock`，完全不访问网络。`ollama` 是一个**显式的本机回环预设**：它复用现有、经过超时/取消/响应大小限制测试的 Chat Completions transport，但只允许连接 `localhost`、`127.0.0.1` 或 `::1`。

项目不会下载模型，也不会启动 Ollama；请先自行让本地服务提供 OpenAI-compatible `/v1/chat/completions` 接口。

最小 `.env`：

```dotenv
AI_BABY_PROVIDER=ollama
AI_BABY_MODEL=填写你本机已有的模型名
```

未设置 `AI_BABY_BASE_URL` 时，`ollama` 默认使用：

```text
http://127.0.0.1:11434/v1
```

这个预设：

- 不需要 `AI_BABY_ALLOW_EXTERNAL=true`，因为地址被强制限制为本机回环；
- 不需要 API key；未填写时不会发送 `Authorization`；
- 绕过系统 HTTP 代理，降低本地记忆被代理意外转发的风险；
- 继续使用已有的超时、取消、大小限制、无重定向和 provider fallback；
- 不会授予模型数据库、文件或工具访问能力。

如果你的本地服务监听不同的回环端口，可以显式设置：

```dotenv
AI_BABY_PROVIDER=ollama
AI_BABY_BASE_URL=http://127.0.0.1:12345/v1
AI_BABY_MODEL=你的模型名
```

`ollama` 预设拒绝远程主机。要连接远程或第三方 OpenAI-compatible 服务，请使用：

```dotenv
AI_BABY_PROVIDER=openai-compatible
AI_BABY_ALLOW_EXTERNAL=true
AI_BABY_BASE_URL=https://example.com/v1
AI_BABY_API_KEY=...
AI_BABY_MODEL=...
```

远程模式的隐私边界与 README / SECURITY.md 中现有说明相同：相关用户输入、档案和检索出的记忆可能被发送给你配置的服务。
