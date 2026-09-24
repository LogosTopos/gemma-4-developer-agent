# Gemma 4 Developer Agent — 逆向工程与 Baseline

[Kaggle 竞赛 gemma-4-developer-agent](https://www.kaggle.com/competitions/gemma-4-developer-agent) 的
**评测框架逆向分析**、**本地校验工具链**，以及一个已验证可提交的 **baseline Agent**。

> 这个竞赛的特殊之处：**参赛者不能提交 Python 代码**。
> 提交物只能是声明式 YAML + 提示词 + 采样参数（+ 可选 LoRA）。
> 所有逻辑都必须表达为「文本与结构」——这正是本仓库关注的边界。

---

## 这个仓库有什么

| 内容 | 位置 | 说明 |
| :--- | :--- | :--- |
| **评测框架源码分析** | [`analysis/HARNESS_SOURCE_ANALYSIS.md`](analysis/HARNESS_SOURCE_ANALYSIS.md) | 1663 行，基于官方分发的 `swegemma` wheel 逐行精读 |
| **研究成果汇总** | [`docs/RESEARCH_SUMMARY.md`](docs/RESEARCH_SUMMARY.md) | 上下文机制、子 Agent 可行性、9 个工具详解、benchmark 证据 |
| **可设计空间清单** | [`docs/AGENT_ARCHITECTURE.md`](docs/AGENT_ARCHITECTURE.md) | 4 种 Agent 类、全部字段、上下文工程杠杆 |
| **模型与通道** | [`docs/MODEL_CHANNEL.md`](docs/MODEL_CHANNEL.md) | 模型家族、特性、三种模型注入方式 |
| **提交格式与校验** | [`docs/SUBMISSION_FORMAT.md`](docs/SUBMISSION_FORMAT.md) | 全部硬闸门、失败模式、格式修复 |
| **行动方案** | [`docs/PLAN.md`](docs/PLAN.md) | 不依赖重训练的分层策略 |
| **Baseline 提交** | [`submission/`](submission/) | 已通过校验并成功提交 |
| **工具链** | [`scripts/`](scripts/) | 下载、修复、校验、打包、端到端回归 |

---

## 快速开始

```bash
git clone <this-repo> && cd gemma_4

# 1) 从 Kaggle 重建环境（需已登录 kaggle CLI）
./scripts/setup.sh --core      # 核心数据约 900MB + wheelhouse + venv
./scripts/setup.sh --snapshots # 追加 20GB 仓库快照（跑真实评测才需要）

# 2) 校验提交包（不需要 GPU、不需要 Docker）
.venv/bin/python scripts/validate_submission.py submission/ --clean

# 3) 打包（校验 → 打包 → 解压复检）
.venv/bin/python scripts/pack_submission.py submission/ -o dist/submission.zip
```

---

## 核心发现

以下几条是**读官方分发源码**得到的，与官方 `HARNESS_README.md` 的表述有出入。

### 1. 判定是两道门，不是一道

官方文档说 `pytest` 退出码为 0 即通过。实际还要求 **JUnit XML 复检**：
failures/errors 必须为 0、passed > 0、`required_nodes` 全部通过
（`verification.py:505-542`，用于防止 `os._exit(0)` 之类的打桩）。

### 2. 自动上下文压缩在分发代码里不存在

官方文档声称配置了 `EventsCompactionConfig(compaction_interval=15, token_threshold=32768, ...)`。
但全树 grep 这些参数**零命中**，`EvalConfig` 里两个相关字段**默认都是 `None`**，
CLI 也没有任何开关。

→ **上下文管理必须自己靠架构做**（`include_contents: none` + `output_key` +
`AgentTool(skip_summarization: true)`）。

### 3. `eval_config.yaml` 根本不会被读取

样例提交里的 `max_time_minutes: 1` / `max_tool_calls: 10` 是误导。
全树 grep `eval_config` 零命中，CLI 也没有 `--config`。

**真实默认预算：单任务 60 分钟 / 工具调用次数无限 / 500 轮 / 单命令 300 秒。**

### 4. `thinking_budget` 不生效，`thinking_level` 才生效

由于 ADK 的 LiteLlm 后端不转发 Google GenAI 的 `thinking_config`，
`adk_submission/resolvers/generation.py:61-116` 只做了一层翻译：

| 写的 | 实际发给 vLLM |
| :--- | :--- |
| `thinking_level: low/medium/high` | `enable_thinking=true` + `reasoning_effort=<level>` |
| `include_thoughts: false` / `NONE` | `enable_thinking=false` |

**`thinking_budget` 这个数字不出现在任何转发路径里。**

### 5. 官方数据有两个坑

- **258 个 0 字节文件**：`graphs/` 与 `embeddings/` 各 256 个文件中约一半是空的
  （zip 无法保存硬链接）。会让 3 个代码智能工具**静默失效**。
  → `scripts/repair_links.py` 修复（从同 commit 的可读副本还原）。
- **图里没有 async 函数**：129 个任务金标触及的 async 函数/方法 **305 个中 0 个**在图中
  （同步函数 4,739/4,740 存在）。fastapi 受影响最大（0/232）。

### 6. `search_similar_code` 有静默陷阱

沙箱内**没有嵌入模型**，实现是拿 query 字符串查 `.npz` 的 key 表。
→ **传自然语言句子返回空列表且不报错**，Agent 会误判为「没有相似代码」。
**必须传符号名。** 更糟的是 `.npz` 损坏时所有向量被填零，相似度全为 0，
`argsort` 退化成节点插入顺序，返回**看起来有结果、实际全是噪声**的答案。

---

## Baseline 设计

```
submission/
├── agent.yaml                    # 根 Agent：9 个内置工具 + 1 个 AgentTool
├── configs/sampling.yaml         # temperature 0.2 / max_output_tokens 8192 / thinking medium
├── prompts/system.md             # 主提示词
├── prompts/locator.md            # 定位子 Agent 提示词
└── sub_agents/code_locator.yaml  # 只读定位子 Agent（4 个只读工具）
```

提示词是**逐条对着实证失败模式**写的：

| 实证发现 | 对策 |
| :--- | :--- |
| 模型输出长分析却不调用工具（"动作脱落"） | `Rule 0 — Act, do not narrate`：每回合必须有工具调用 |
| 读对了文件但取错字段 | 要求先读相邻函数/测试文件对齐约定 |
| 在零数据上宣告成功 | 提交前必须确认 `patch_size > 0` 且 `files_changed > 0` |
| `search_similar_code` 静默返回空 | 显式写明"空结果 = 查询写错，不是没有代码" |
| 图里无 async 节点 | "遇到 `async def` 直接放弃图工具，用 grep" |
| 改测试文件会被静默丢弃 | 硬禁止清单 |
| scratch 文件会混进 patch | "一律写 `/tmp/`" |
| 命令失败后反复重试 | 8 行「症状 → 修复」对照表 |

三个刻意的取舍：
- `max_output_tokens` 从默认 16384 **降到 8192**，把省下的窗口留给工具结果
- `thinking_level: medium` 而非 `high`，缓解动作脱落
- `skip_summarization: true`，子 Agent 的探索噪声不进主上下文

---

## 工具链

```bash
# 从 Kaggle 拉数据（按清单，并还原 Kaggle CLI 拉平的目录结构）
python3 scripts/fetch.py --list /tmp/allfiles.csv --pattern '^graphs/'

# 修复 0 字节的 graph/embedding
python3 scripts/repair_links.py --manifest /tmp/allfiles.csv

# 静态校验：目录结构 / 硬闸门 / 单模型规则 / 编译成 ADK agent 树
.venv/bin/python scripts/validate_submission.py submission/ --clean

# 打包：校验 → 打包 → 解压复检
.venv/bin/python scripts/pack_submission.py submission/ -o dist/submission.zip

# 端到端回归：假 LLM 驱动真实 harness 走完整管线
.venv/bin/python scripts/mock_llm_server.py --port 8111 &
.venv/bin/python scripts/e2e_local_test.py fastapi_11194
```

**校验器能抓到什么**（都实测过）：
拼错的 YAML 键（`extra="forbid"`）、多模型声明、`.DS_Store` / 无扩展名文件 / 符号链接。

**端到端测试证明的链条**：提交包能编译 → `subprocess` 沙箱能起 → 工具能被调用 →
文件能被修改 → patch 能被抽取且非空 → Phase 2 能在干净沙箱里跑 pytest。

---

## 环境说明

- **本机（macOS / Apple Silicon）**：可以完整做**静态校验**与**端到端管线回归**，
  因为 `swegemma` / `adk_submission` / `google-adk` 都是纯 Python wheel。
- **跑不了**：真实任务推理。官方评分机是 4×NVIDIA L4 + vLLM，
  本机没有 NVIDIA GPU，也装不了 wheelhouse 里的 `vllm` / `bitsandbytes`（x86_64 only）。
- 想拿真实分数：提交到 Kaggle，或用 **12B 代理模型**在免费 GPU 上做相对比较。

`.venv` 里安装的是**官方 wheelhouse 的包**，因此校验规则与评测端一致。

---

## 免责与致谢

- 本仓库是**独立的第三方分析**，与 Google / Kaggle 无隶属关系。
- 竞赛数据、Harness 文档、评测框架（`swegemma` / `adk-submission` / `adk-eval-core`）
  版权归主办方所有，**不随本仓库分发**，请通过 `scripts/setup.sh` 从 Kaggle 自行获取。
- 引用的第三方论文为独立研究，未随仓库分发，链接见 `docs/RESEARCH_SUMMARY.md`。
- 分析基于 `swegemma 0.2.7` / `adk-submission 0.2.11` / `adk-eval-core 0.1.0`，
  主办方可能随时更新——**以你自己拉到的版本为准**。

## 许可

本仓库原创内容（分析文档、脚本、baseline 配置）采用 MIT 许可。
竞赛数据与官方框架不在许可范围内。
