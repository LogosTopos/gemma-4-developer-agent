> **历史分析（保留原文，2026-09-28 已有更正）。** 本文中的提交限制、预算、评分和运行能力判断可能已过期；执行前以 [当前研究状态](../docs/RESEARCH_STATUS.md) 与 [实验交接计划](../docs/EXPERIMENT_HANDOFF.md) 为准。skill Python 可提交、外层 scorer 读取四个 eval_config 字段、模拟回放不是模型能力实测。

# 提交格式：校验与修复

这里有两件完全不同的事，容易混为一谈：

| | 提交物 | 格式风险 | 谁来校验 |
| :--- | :--- | :--- | :--- |
| **A** | Agent 在评测中产出的 **git 补丁** | 低（git diff 本身就规范） | 评测框架，失败即 0 分 |
| **B** | 我们上传给 Kaggle 的 **submission.zip** | **高**（十几条硬闸门） | `compile_submission`，失败即拒收 |

## A. Agent 的补丁提交

### 机制

`submit_patch()` 做的事就一条：

```bash
cd /workspace && git add -N . && git diff HEAD
```

`git add -N .`（intent-to-add）让**新建的未跟踪文件**也进入 diff，
同时 `.git/info/exclude` 里的 `__pycache__/` `*.pyc` `.pytest_cache/` `*.egg-info/`
`build/` `dist/` `.coverage` 会被自动排除。

→ **格式层面几乎不会错**。它就是一个标准 unified diff。

### 真正的失败模式（都不是"格式"问题）

| 失败模式 | 后果 | 对策 |
| :--- | :--- | :--- |
| patch 为空（`""`） | 直接 0 分，不进 Phase 2 | prompt 强制要求确认 `patch_size > 0` |
| 改了测试文件 | 被 `git checkout HEAD -- <files>` **静默丢弃** | prompt 明令禁止；反正也没用 |
| 把 scratch 脚本留在 `/workspace` | 一起进 patch，可能干扰 | 规定 scratch 一律写 `/tmp/` |
| 改了 `pytest.ini` / `conftest.py` | harness 生成的文件进了 diff | prompt 明令禁止 |
| diff 太大 / 改错文件 | 4 次 apply 兜底也可能失败 | 最小改动原则 |
| 没调 `submit_patch` 就结束 | **仍有救**：harness 会自动跑一次 `git add -N . && git diff HEAD` | 不必强求一定调用 |

关键洞察：**patch 抽取是自动的、有兜底的**（`agent_runner.py:706-740`），
而且 `agent_error` 存在但 patch 非空时**仍然进 Phase 2**。
→ 所以策略上「**尽早产生一个大致正确的 diff**」比「追求完美再提交」期望收益更高。

### 已有的格式修复能力（框架自带）

`edit_file` 的 **3 层容错匹配**本质上就是"写错了自动帮你修"：

1. `exact` —— 逐字符精确匹配
2. `flexible` —— 逐行 strip 后匹配，并自动重排缩进
3. `regex` —— 按代码分隔符 token 化，容忍换行/空格差异

⚠️ 但有个反直觉的坑：**任一层只要"匹配到多个"就立即失败返回，不会继续降级**。
只有"0 命中"才降级。所以 `old_string` 必须唯一。

## B. submission.zip 的格式校验

### 硬闸门清单（违反任一条 = 拒收）

```
□ 根配置唯一：agent.yaml > root_agent.yaml > 顶层唯一 .yaml/.yml
  （agent.yaml 与 root_agent.yaml 并存不报错，agent.yaml 胜出）
□ 扩展名白名单仅 7 种：.yaml .yml .md .txt .py .json .safetensors
  ⚠️ 无扩展名文件（Makefile / LICENSE / .gitignore）一律被拒
  ⚠️ LoRA 权重必须 .safetensors（.bin / .pt / .gguf 被拒）
□ 目录树内任何符号链接 → 直接拒
□ 绝对路径 / .. 穿越 / Windows 盘符 → PathTraversalError
□ !include 深度 ≤ 10
□ 所有 Pydantic 模型 extra="forbid" → 拼错的键是硬失败
□ LlmAgent 必须声明 instruction
□ 单模型规则：全树归一化后只能有一个基座模型
□ thinking_budget ∈ [0, 32768]；max_output_tokens ∈ [1, 32768]
□ 总解压大小 < 3 GiB；文件数 ≤ 10,000；YAML 数 ≤ 1,000
□ 单 YAML ≤ 50 MiB；单 skill 目录 ≤ 50 MiB
□ instruction 单个 ≤ 1e6 字符；全体累计 ≤ 1e7 字符
□ max_agents ≤ 500；sub_agent 深度 ≤ 50；skills ≤ 1000
```

### 校验怎么做（本地可完全跑通）

`swegemma` / `adk_eval_core` / `adk_submission` / `google_adk` 都是
**`py3-none-any` 纯 Python wheel**——在 M4 Mac 上装得起来（不需要 CUDA）。
所以我们可以**在本地复刻一遍完整的提交校验**：

```python
from swegemma.config import build_submission_limits
from adk_submission import compile_submission, validate_directory, ToolRegistry
from swegemma.models.discovery import validate_single_declared_model

limits, gen_constraints = build_submission_limits()

# 1) 结构检查：符号链接、大小、文件数、扩展名白名单、根配置唯一性
#    （adk_submission/discovery.py:60）
submission_dir = validate_directory("submission/", limits=limits)

# 2) 单模型规则（swegemma/models/discovery.py:93）
model = validate_single_declared_model("submission/")

# 3) 真正编译成 ADK agent 树 —— 同时验证 YAML 语法、!include 解析、
#    extra="forbid" 的拼写错误、tools 名是否在注册表内、生成参数范围
agent = compile_submission(
    submission_dir="submission/",
    tool_registry=ToolRegistry(),          # 本地可为空 dict，只要工具名对得上
    model_registry=model_registry,         # 别名需已注册
    limits=limits,
    generation_constraints=gen_constraints,
)
```

> 本地校验时 `tool_registry` 可以是任意 `dict[str, Callable]`，
> 因为这一步只检查**工具名是否被声明过**，不会真的调用它们。
> 所以不需要真的能把沙箱跑起来，就能完成全部静态校验。

**这是零 GPU 依赖、当天就能做完的事**，而且能拦住"辛苦做完却被拒收"这种最亏的情况。

建议做成 `scripts/validate_submission.py`，在每次改动后跑一遍。

### 格式修复怎么做

- **YAML 语法/缩进**：不需要自动修复，直接改。`!include` 报错信息足够明确。
- **扩展名问题**：`Makefile` / `LICENSE` 这类文件**不要放进提交包**——
  它们对评测毫无用处，且会被直接拒收。
- **符号链接**：打包时用 `zip`（不跟符号链接）而非 `tar -h` 之外的方式；
  或者提交前扫描一遍 `os.path.islink`。
- **建议**：写一个 `scripts/pack_submission.py`，
  先跑校验 → 通过后用 `zip` 打包 → 再解压到临时目录复检一遍。

## C. 关于 `thefuck` 那类"自动纠正输错的命令"

**结论：思路有价值，但这个具体项目不能直接用。** 逐条说明原因。

### 为什么不能直接用

1. **它是 CLI 交互工具，不是库**。`thefuck` 的工作方式是 shell 别名 → 捕获上一条失败命令 →
   选择规则 → 让用户在 TTY 里确认 → 执行。评测里 **Agent 不会打字**，
   而且 `run_command` 是我们从框架拿到的一个函数，**没有 TTY、没有 shell 钩子**。
2. **它高度依赖交互确认**，非交互模式（`--yeah`）只能盲执行，
   而我们无法保证修正后的命令是对的——盲执行一条错误命令反而烧掉 300 秒超时。
3. **它的 LLM 增强路径（`llm` 规则）需要联网**，
   而 Container A 是 **`network_mode="none"` 完全断网**。这条最强的能力直接没了。
4. **最致命的一条：我们无法插入自定义工具。**
   `ToolRegistry` 是**封闭的**，`swegemma.create_tools()` 固定返回那 9 个工具，
   由主办方在评测端构建。参赛者只能在 `agent.yaml` 的 `tools:` 里**勾选**，
   **不能注册新工具**。没有注册点，就没有接入点。
5. **skills 也指望不上**：`skills/` 里的 `.py` 在白名单内，但
   `compile_submission` 的 `code_executor` 是**可选参数且由主办方注入**
   （注释："Optional sandboxed code executor for running agent skills"）。
   评测壳未分发，我们**无法确认 skill 脚本是否真的会被执行**。
   把关键逻辑押在这上面风险太高。

### 但它的"内核"可以用别的方式实现

`thefuck` 真正的价值不是代码，而是**一组确定性的「错误 → 修正」规则**。
我们可以把这组规则**写进 prompt**，效果等价，且零风险：

```markdown
## 命令失败时的修正规则（对照表）
- `cd /workspace/x && cmd` 报路径不存在 → 不要用 `cd`，工具已在 /workspace 下执行
- 裸 `pytest` / `pytest .` → 禁止；必须指定具体测试文件
- `pip install ...` → 环境离线，必然失败，不要重试
- `grep -r` 无结果 → 改用 `read_file` 或 `search_similar_code`（注意后者只吃符号名）
- 命令超时（300s） → 拆小命令，不要重跑同一条
- `edit_file` 报 "matches more than 1 occurrence" → 扩大 old_string 上下文，重试
- `read_file` 返回 is_truncated → 用 start_line/end_line 分段，不要重复读同一段
```

**另一点值得注意**：框架**已经内置了两个同类机制**，说明主办方也认可这个方向——

1. **3 类自动 nudge**：当 Agent 因为 token 上限把 `<|tool_call>` 写断，
   或思考太长没发出工具调用时，harness 会**自动注入修正提示**：

   | 触发 | 注入内容（逐字，已确认） |
   | :--- | :--- |
   | `<\|tool_call>` 被截断 | "Your previous response reached the token limit before the tool call finished closing (`<\|tool_call\|>` was cut off). Do NOT repeat your prior reasoning in thought—emit your next tool call immediately, and if calling edit_file or write_file, split the change into smaller incremental edits." |
   | `finish_reason` 含 MAX_TOKENS/LENGTH | "Your previous response reached the token limit while thinking before a tool call was completed. Do NOT repeat your analysis in thought—keep reasoning under a few sentences and emit your next tool call immediately, or call submit_patch when you have completed and verified your changes." |
   | 正常停轮但没提交 | "Please continue your work using the available tools, or call submit_patch when you have completed and verified your changes." |

2. **`edit_file` 的 3 层容错匹配**——本身就是"写错了帮你兜"。

→ 所以在这个框架里，**"自动纠正"的正确形态是 prompt 规则，而不是一段代码**。
这也正好呼应了本竞赛的根本设计：**不给你写代码的机会**。
