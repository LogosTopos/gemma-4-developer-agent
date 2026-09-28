> **历史分析（保留原文，2026-09-28 已有更正）。** 本文中的提交限制、预算、评分和运行能力判断可能已过期；执行前以 [当前研究状态](../docs/RESEARCH_STATUS.md) 与 [实验交接计划](../docs/EXPERIMENT_HANDOFF.md) 为准。skill Python 可提交、外层 scorer 读取四个 eval_config 字段、模拟回放不是模型能力实测。

# Agent 架构：可设计空间清单

> 全部来自 `adk_submission-0.2.11` 的 Pydantic schema 与 `swegemma-0.2.7` 的编译/运行逻辑。
> 所有模型 `extra="forbid"`——**拼错的键是硬失败**，不是警告。

## 一、提交物的四种 Agent 类

根配置按 `agent_class` 判别，共 4 种，可任意嵌套：

| `agent_class` | 语义 | 专有字段 |
| :--- | :--- | :--- |
| `LlmAgent`（默认） | 真正调用模型的推理单元 | 见下表 |
| `SequentialAgent` | 子 Agent 顺序执行 | `sub_agents` |
| `ParallelAgent` | 子 Agent 并发执行（分支隔离） | `sub_agents` |
| `LoopAgent` | 重复执行子 Agent | `sub_agents` + `max_iterations`（1–500，默认 500） |

### `LlmAgent` 的全部可配置字段

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `name` | str | **必填**，标识符 |
| `model` | str | 模型别名（单模型规则约束） |
| `adapter` | str \| None | 指向 `adapters/<name>/` 的 LoRA |
| `description` | str | 父 Agent 委派时看到的说明（≤1,000,000 字符） |
| `instruction` | str | **必填**，系统提示词。支持 ADK 状态模板插值 |
| `tools` | list | 工具名 / `AgentTool` / 内联 agent 字典 |
| `skills` | list[str] \| None | ADK skill 目录相对路径 |
| `sub_agents` | list | `{config_path: ...}` 引用，支持 transfer 委派 |
| `output_key` | str \| None | 把本 Agent 最终输出写入 `session.state[key]` |
| `include_contents` | `"default"` \| `"none"` | 是否把对话历史喂给本 Agent |
| `disallow_transfer_to_parent` | bool \| None | 禁止向上委派 |
| `disallow_transfer_to_peers` | bool \| None | 禁止同级委派 |
| `generate_content_config` | dict \| None | 采样与思考参数 |

### 状态模板（很重要的一个机制）

Harness 在 `session.state` 里预置：

- `problem_description` ← `task.problem_statement`
- `hints` ← `task.hints_text`（**本地 129 个任务全为空**，官方测试集未知）

ADK 会自动把 `instruction` 里的 `{变量名}` 替换成 state 值。
配合 `output_key`，就能做**显式的阶段间数据流**：

```yaml
# 分析 Agent 把结论写进 state
name: analyzer
output_key: analysis_report
instruction: !include prompts/analyzer.md

# 编码 Agent 只读结论，不读原始探索噪声
name: coder
include_contents: none          # ← 关键：切断历史，只吃结构化结论
instruction: |
  问题：{problem_description}
  分析结论：{analysis_report}
  ...
```

这两行（`output_key` + `include_contents: none`）是**上下文工程最有力的杠杆**：
能把子 Agent 的探索过程完全挡在主 Agent 的上下文之外，只传递压缩后的结论。
在 32k 硬顶下，这直接决定 Agent 能跑多远。

## 二、`tools` 的三种写法

```yaml
tools:
  - run_command                    # 1. 按名字引用注册表里的内置工具
  - agent_tool:                    # 2. 把子 Agent 包成工具
      config_path: sub_agents/code_analyzer.yaml
      skip_summarization: true     # ← 子 Agent 的中间过程不进主上下文
  - name: inline_tool              # 3. 内联 agent 字典
    description: ...
```

⚠️ **工具注册表是封闭的**：`ToolRegistry` 只含 `swegemma` 注册的那 9 个工具，
由主办方在评测端构建。**参赛者无法新增自定义工具函数**——我们只能"勾选"这 9 个。
这是理解整个设计空间的关键约束。

可勾选的 9 个：

```
run_command  read_file  write_file  edit_file  submit_patch  get_status
get_code_neighbors  search_similar_code  get_code_subgraph
```

## 三、`generate_content_config`（采样与思考）

```yaml
temperature: 0.2          # 任意合法值
top_p: 0.95               # 0.0–1.0
top_k: 32                 # >=1
max_output_tokens: 16384  # 1–32768，默认注入 16384
presence_penalty / frequency_penalty / stop_sequences / seed
thinking_config:
  thinking_level: high    # MINIMAL | LOW | MEDIUM | HIGH | NONE
  thinking_budget: 4096   # 默认注入 4096
  include_thoughts: true
```

被**设计性排除**的字段（设了直接校验失败）：
`tools` / `system_instruction` / `http_options` / `safety_settings` / `response_schema`。

### ⚠️ `thinking_budget` 的真实作用（源码结论）

`adk_submission/resolvers/generation.py:61-116` 的 `apply_thinking_config_to_model()`
说明：ADK 的 LiteLlm 后端**不会**把 Google GenAI 的 `thinking_config` 转发给
OpenAI 兼容端点（即 vLLM）。它只做如下翻译：

| 你写的 | 实际发送给 vLLM |
| :--- | :--- |
| `thinking_level` ∈ {low, medium, high} | `extra_body.chat_template_kwargs.enable_thinking=true` + `reasoning_effort=<level>` |
| `thinking_level: minimal` | 仅 `enable_thinking=true`（**不发送** reasoning_effort） |
| `include_thoughts: false` 或 `thinking_level: NONE` | `enable_thinking=false`，并移除 reasoning_effort |

→ **`thinking_budget` 这个数字没有出现在任何转发路径里**。真正的旋钮是
`thinking_level` 与 `include_thoughts`。这是官方 README 没讲清的地方。

（`thinking_budget` 仍受 schema 范围 `[0, 32768]` 校验，超范围会硬失败。）

## 四、`skills/`（唯一可能放 Python 的地方）

```
skills/
└── repo_navigation/
    └── SKILL.md          # 必需
    └── *.py              # 允许扩展名，但是否执行取决于主办方是否注入 code_executor
```

`compile_submission` 有 `code_executor` 与 `script_timeout` 参数，注释写的是
"Optional sandboxed code executor for running agent skills"。
**主办方是否传这个参数，我们在本地代码里看不到**（评测壳未分发）。
→ 保守假设：**不要把关键逻辑押在 skill 脚本上**。
`.py` 在白名单里，但"能提交"不等于"会被执行"。

## 五、其它约束

- `!include` 指令：`.md`/`.txt` 原样读取，`.yaml`/`.yml` 递归解析（深度 ≤10）
- 禁止：绝对路径、`..` 穿越、符号链接、空字节
- `max_agents` 500 / `max_subagent_depth` 50 / `max_skills` 1000
- `instruction` 单个 ≤1,000,000 字符，全体累计 ≤10,000,000 字符
- **单模型规则**：树里所有 Agent 必须共用同一个基座模型（`adapter` 可以不同）
- 总解压大小 < 3 GiB（含 `adapters/`）

## 六、架构设计上真正值得投入的杠杆

按预期收益排序：

1. **`output_key` + `include_contents: none` 的组合**——显式数据流，最直接地对抗 32k 上限
2. **`AgentTool` + `skip_summarization: true`**——把探索型子 Agent 的噪声挡在主上下文外
3. **工具的差异化分配**——探索型 Agent 只给只读工具（`read_file`/图工具），
   编辑型 Agent 才给 `edit_file`/`write_file`，减少误操作面
4. **`thinking_level` 的选择**——high 提升推理质量但吃 token；配合 32k 上限需要实测
5. **`instruction` 的分工**——根 Agent 做决策与提交，子 Agent 做定位与验证
6. `LoopAgent` 的自我修正循环（注意 500 次上限与会话 60 分钟墙钟的交互）
7. `ParallelAgent` 并发探索多个假设（但子 Agent 共享同一 vLLM，吞吐可能反而下降）
