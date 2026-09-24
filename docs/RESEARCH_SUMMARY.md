# 研究成果汇总

> 时间：2026-09-24 · 依据：官方分发源码 + 官方数据 + 外部公开资料
> 标注约定：**【源码实证】** = 我读代码确认；**【外部资料】** = 联网来源，可信度另注；**【推断】** = 我的结论

---

## 一、32k 是「每次请求」上限，不是「每任务」上限

### 结论

**可以做手动的上下文管理，而且必须做——因为框架不会帮你做。**

### 证据链

**【源码实证】官方 README 声称的自动压缩，在分发的代码里不存在。**

README §7.2 写着 `EventsCompactionConfig(compaction_interval=15, overlap_size=2,
token_threshold=32768, event_retention_size=5)` 与 `ContextCacheConfig(...)`
且说 "`swegemma` configures ... on the `App` instance (`metric/scoring.py`)"。

但实际代码是：

| 位置 | 事实 |
| :--- | :--- |
| `swegemma/config.py:116-117` | `context_cache_config` / `events_compaction_config` **默认都是 `None`** |
| `swegemma/cli.py` | **没有任何** `--compaction` / `--cache` 参数（grep 零命中） |
| `adk_eval_core` / `adk_submission` | 全树 grep `compaction_interval` / `overlap_size` / `token_threshold` / `event_retention_size` → **零命中** |
| `agent_runner.py:408-411` | 只有非 None 才传给 `App`；否则用 ADK 默认 |
| ADK `App.__init__`（实测） | `events_compaction_config: Optional[...] = None` |

→ **那些参数在分发的代码里根本不存在**。README 说的 `metric/scoring.py` 是 Kaggle 侧未分发的壳。
**我们无法确认官方评测时是否真的开了自动压缩**（这是第三次发现 README 与源码不符）。

### 32k 到底限制什么

它限制的是 **vLLM 的 `max_model_len`**，即**单次 LLM 请求**的 prompt+thinking+输出总长。
**不是**整个任务只能处理 32k。

- 一个任务有很多轮（上限 500 turns / 60 分钟）
- 每一轮都会把**累积的对话历史**重新送进模型
- 所以任务总处理量可以远超 32k，**但单轮的累积历史不能超**

**这就是为什么上下文管理 = 架构设计的核心问题。**

### 预算实测（我跑了真实的 prompt 构造函数）

用 `build_agent_prompt()` 对 129 个任务实测：

| 项目 | 大小 | 占 32k |
| :--- | ---: | ---: |
| 固定初始 prompt（预算+环境规则+指令） | ≈ 548 tok（中位 1,809 字符） | 1.7% |
| \+ workspace 树（最多 150 条目） | ≈ 1,500 tok | 4.6% |
| \+ 图工具说明段 | ≈ 100 tok | 0.3% |
| **固定开销小计** | **≈ 2,148 tok** | **6.6%** |

**真正的敌人不是 prompt，是工具返回的原始文本**：

| 单次调用 | 上限 | 折合 |
| :--- | ---: | ---: |
| `read_file` | 10,000 字符 / 150 行 | **≈ 2,500 tok** |
| `run_command` 输出 | 5,000 字符 | **≈ 1,250 tok** |
| 模型单次输出 | `max_output_tokens` 默认 16,384 | **16,384 tok** |

→ **约 12 次 maxed `read_file` 就塞满整个窗口。**

### 我们实际能做的手动压缩手段

| 手段 | 字段/工具 | 效果 |
| :--- | :--- | :--- |
| **切断子 Agent 历史** | `include_contents: none` | 该 Agent 每次调用都是干净的，不累积 |
| **摘要化子 Agent 输出** | `AgentTool` + `skip_summarization: true` | 中间 read_file 输出**不进主上下文** |
| **显式跨 Agent 数据传递** | `output_key` + `{变量}` 插值 | 只传压缩后的结论 |
| **用文件当外部记忆** | 子 Agent `write_file` 写 `/tmp` | 主 Agent 按需读取，而非全部驻留 |
| **写进 prompt 的硬规则** | — | 禁止重复读同一段、禁止全量 grep、禁止裸 pytest |

⚠️ **没有自动兜底**：一旦累积历史顶到 32k，唯一机制是 harness 的 **3 次 nudge**
（见 `docs/SUBMISSION_FORMAT.md` 的 nudge 表），提示模型"别重复推理、立刻发工具调用"。
**超过 3 次连续无工具调用的轮次，会话直接终止。**

---

## 二、子 Agent 审核工具调用：部分可行，但不是你设想的那个形态

### 逐条回答

| 你的设想 | 能否实现 | 原因 |
| :--- | :---: | :--- |
| 主 Agent 设计/发出命令 | ✅ | `run_command` 就是干这个的 |
| 子 Agent 审核命令正确性 | ✅ | 用 `agent_tool` 把审核 Agent 包成工具 |
| **主 Agent 发完就去干别的** | ❌ | **ADK 的工具调用是同步的**，模型发出 tool call 后会阻塞等待结果 |
| 相当于"后台运行" | ❌ | 框架没有 async tool / fire-and-forget 机制 |
| **加一层屏障** | ⚠️ 部分 | 审核者只能给「建议」，**最终命令仍由主 Agent 执行** |
| 屏障能减少上下文污染 | ❌ | 命令输出照样进主 Agent 上下文 |

**结论：能拿到"审核"（同步），拿不到"后台/异步"。**

### 关于"轻量级"这个词的精确含义

⚠️ **单模型规则锁死了基座**——所有 Agent 必须用同一个模型（`validate_single_declared_model`）。
所以"轻量级子 Agent"**不可能**靠换小模型实现。它只能是：

- **短 prompt**（几百 token 而非几千）
- **极少工具**（只给 `read_file`，不给 `edit_file` / `run_command`）
- **极小输入输出**（只收一条命令 + 少量上下文，只回一个裁决）

这才是可行的"轻量级"。

### 一个结构性限制：审核建议 ≠ 阻止错误

即使审核子 Agent 说"这条命令错了"，**命令的执行权和错误后果仍在主 Agent 手里**。
审核只把"试错"变成了"多一次模型调用 + 仍然可能照跑"。

而 `run_command` 失败本身代价很低——它返回 `{"status":"error", "error_type":"CommandError", ...}`
**不结束会话**（只有整体时间预算耗尽才结束）。

### 支持派 vs 反对派的证据

**支持多 Agent 的**：
- 官方 README 明确把它列为最佳实践（§10.4，`AgentTool` + `skip_summarization` 隔离上下文）
- 子 Agent 拥有**独立的 32k 窗口**——这才是多 Agent 的真正理由（**上下文隔离，不是速度**）

**反对派的**（证据更硬）：

**【外部资料】一篇直接相关的论文**（见 §五）：在 31B 模型上，**改编排器**带来 4.5× 提升
（0.8/10 → 3.6/10，模型不变）。而他们**取胜的配置是：单个编排器 + 200 token 提示词 + 只给 6 个工具，
完全没有子 Agent**。

**【推断】小模型委派能力弱**：32k 的模型要判断"何时该委派""怎么问子 Agent""怎么理解返回"，
这些本身就是认知负担。**委派失败的代价可能大于收益。**

### 我的建议

| 做法 | 评价 |
| :--- | :--- |
| 开放式多 Agent 树 | ❌ 先在代理模型上证明它比单 Agent 好，否则不做 |
| **单个窄职责子 Agent**（如"定位器"） | ✅ 值得试，且要**确定性触发**（"永远用错误里的符号名调用它"），而非让模型自行判断 |
| **把规则写成 prompt 对照表** | ✅ **最高性价比** —— 即上次讨论的 thefuck 内核方案。确定性、零 token 开销、零延迟 |
| 只对高风险动作做审核 | ⚠️ 可选。如"第一次 `pip install`""裸 `pytest`""`cd` 链" |

**一句话**：你的"审核屏障"想法在架构上能搭，但**在 32k 小模型上，把同样的规则写进
主 Agent 的 prompt 里，期望收益更高、成本更低**。多 Agent 的正确定位是**上下文隔离工具**，
不是"并行加速"或"质量把关"。

---

## 三、9 个内置工具

全部来自 `swegemma/tools/{execution,workspace,graph}.py`。
统一返回 JSON：成功 `{"status":"ok", ...}`；失败 `{"status":"error","error_type":...,"error_message":...}`。

### 执行与生命周期

| # | 工具 | 说明 | 计费 |
| :-: | :--- | :--- | :-: |
| 1 | **`run_command(command)`** | 在 `/workspace` 下跑 `bash -c`，超时 `min(300s, 剩余时间)`。stdout/stderr 各截断 5,000 字符。失败返回 `CommandError` **但不结束会话** | 是 |
| 2 | **`submit_patch()`** | `git add -N . && git diff HEAD`，存入 `ctx.submitted_patch`，置 `patch_submitted=True`。返回 `{"patch_size":..., "files_changed":...}` | **否** |
| 3 | **`get_status()`** | 返回 `tool_calls_used` / `patch_submitted` / `time_seconds_remaining` / `max_turns` 等 | **否** |

### 工作区文件操作

| # | 工具 | 说明 | 计费 |
| :-: | :--- | :--- | :-: |
| 4 | **`read_file(filepath, start_line?, end_line?)`** | 1-indexed 闭区间切片。**双重截断：150 行 AND 10,000 字符**，触发则 `is_truncated=true` 并回传实际 `end_line` | 是 |
| 5 | **`edit_file(filepath, old_string, new_string, allow_multiple=False)`** | **3 层容错匹配**：`exact` → `flexible`（逐行 strip + 自动重排缩进）→ `regex`（按 `()[]{}><=:` 等分隔符 token 化）。⚠️ **任一层匹配到多个立即失败，不降级**；只有 0 命中才降级 | 是 |
| 6 | **`write_file(filepath, content)`** | 创建/覆盖，自动 `mkdir -p` 父目录 | 是 |

### 代码智能（图与嵌入）

| # | 工具 | 说明 | 计费 |
| :-: | :--- | :--- | :-: |
| 7 | **`get_code_neighbors(node, edge_type?, max_neighbors=50)`** | 查符号的入/出邻居（callers、callees、definitions）。`resolve_node_name` 四级匹配：精确 → `.`/`;` 后缀 → 大小写不敏感 → 子串 | 是 |
| 8 | **`search_similar_code(query, k=10)`** | ⚠️ **只接受符号名**。沙箱内**没有嵌入模型**，实现是拿字符串查 `.npz` 的 key 表。**传自然语言返回空列表且不报错** | 是 |
| 9 | **`get_code_subgraph(nodes)`** | 一组符号的诱导子图（节点 + 连边） | 是 |

### 三条必须记住的坑（源码实证）

1. **`search_similar_code` 的静默失败**：传自然语言 → `{"status":"ok","results":[],"count":0}`。
   Agent 极易误判为"没有相似代码"。
2. **`.npz` 损坏时的静默噪声**：每个节点向量被填 `np.zeros(128)` → 所有相似度 = 0 →
   `argsort` 退化成**节点插入顺序**，返回"图里最前面的 k 个节点"。**看起来有结果，全是噪声。**
3. **图里没有 async 函数**：129 个任务金标触及的 async 函数/方法 **305 个中 0 个**在图中
   （同步函数 4,739/4,740 存在）。fastapi 受影响最大（0/232）。

### 预算提醒机制

当 `budget.tool_calls >= 20` 且剩余 ≤ 10 时，**每个工具返回**会自动附加：

```json
"budget_warning": "Only X tool call(s) remaining (Y/Z used). Finalize your edits and call submit_patch soon."
```

---

## 四、对 32k 小模型，多子 Agent 架构真的有效吗？

### 诚实的回答：**证据不足，且现有最强证据指向"不"**

**多 Agent 唯一站得住脚的理由是上下文隔离**——每个子 Agent 有独立的 32k 窗口，
子 Agent 的探索噪声不污染主 Agent。

**但它有三个硬成本**：

1. **串行延迟**：ADK 工具调用同步。所有 Agent 共享同一个 vLLM 实例
   （`tensor_parallel_size=4` 吃掉全部 4 张卡），子 Agent 调用 = 主 Agent 干等。
2. **token 二次消耗**：委派指令 + 子 Agent 的推理 + 返回摘要，全都要花 token。
3. **委派能力本身是稀缺资源**：32k 模型要判断"何时委派/怎么问/怎么理解返回"。

**【外部资料】最相关的实证正好站在反对面**（详见 §五）：31B 模型上，
**单编排器 + 200 token prompt + 6 个工具 + 零子 Agent** 是最佳配置，得分 4.5× 于弱编排器。

### 但有一个重要的反驳

那篇论文的编排器是 **Claude Sonnet 4.6**（一个很强的模型）驱动本地 31B 生成动作。
我们的场景是 **31B 自己当编排器**。这有本质差别：

- 强编排器 + 弱后端 → 单 Agent 最优（编排智能在外挂）
- **弱编排器 + 弱后端（我们）** → 结构化分工**可能**反而有帮助，
  因为它把"自由发挥"变成"填空"

→ **所以这是一个必须实测的经验问题，不能靠推断下结论。**
我的判断：**从单 Agent 起步，把多 Agent 当作有明确假设的对照实验**，而不是默认架构。

---

## 五、模型的 benchmark 成绩

### Gemma 4 31B（竞赛默认基座）

**【外部资料】[RankedAGI](https://rankedagi.com/models/gemma-4-31b)**（第三方聚合站，2026-04 发布）：

| Benchmark | 分数 | 排名 |
| :--- | ---: | ---: |
| **SWE-bench Verified** | **80.9%** | #4 |
| SWE-bench Multilingual | 51.7% | #19 |
| SWE-bench Pro | 35.7% | #42 |
| Terminal Bench 2.0 | 42.9% | #34 |
| LiveCodeBench v6 | 80.0% | #17 |
| Code RankedAGI | 59.5% | #70 |
| Agentic RankedAGI | 52.2% | #79 |
| MMLU Pro | 85.2% | #11 |
| GPQA Diamond | 84.3% | #36 |
| AIME 2026 | 89.2% | #12 |

**注意 SWE-bench 三个版本的巨大落差：Verified 80.9% vs Pro 35.7%。**
Verified 是筛选过的经典任务，Pro 是更难的真实任务。**竞赛任务更接近哪种，需要自己判断。**

### Gemma 4 12B IT（我们打算用的代理模型）

**【外部资料】[LLM Reference](https://www.llmreference.com/model/gemma-4-12b-it)**：

| Benchmark | 分数 | 对照：31B |
| :--- | ---: | ---: |
| MMLU Pro | 77.2 | 85.2 |
| LiveCodeBench v6 | 72.0 | 80.0 |
| GPQA Diamond | 78.8 | 84.3 |
| AIME 2026 | 77.5 | 89.2 |

12B 相对 31B 大致是"低 8–12 个百分点"。**足够做相对比较，不适合估绝对分。**

### ⚠️ 最关键的观察：80.9% vs 0.12

**Gemma 4 31B 在 SWE-bench Verified 上是 80.9%（第 4 名），
而本竞赛的排行榜榜首只有 0.12。**

这个落差**不是模型能力问题**。它说明瓶颈在别处：

- 上下文被限制到 **32k**（模型自身支持 256k）
- **只给 9 个工具**，且强推理工具（`search_similar_code`）实际退化成了字符串查表
- 用的是**自研 harness**，不是成熟脚手架
- 单任务 60 分钟 / 单命令 300 秒

**【外部资料】一项研究直接量化了这一点**（[论文 PDF](https://huggingface.co/api/resolve-cache/datasets/KikoCis/real-world-agent-benchmark/c6691cc8f60e154a8470820b83f33908ca49e68d/paper4_orchestrator_dominance.pdf)，
Cisneros & Sonnet 4.6, 2026-05, [代码](https://github.com/KikoCisBot/gemma4-31b-study)）：

| 发现 | 数据 |
| :--- | :--- |
| **换编排器，模型不变** | 0.8/10 → **3.6/10（4.5×）** |
| **任务描述写详细** | 2.0 → **7.4（3.7×）** |
| **微调反而更差** | base 7.4 vs 微调版 5.6（**-32%**） |
| "benchmark 陷阱" | E4B 在 BFCL 刷到 95.5%，真实任务 **0/10**；未微调版反而 3/10 |

**这直接支持我们的两条核心策略**：
1. **优先投入 prompt 与架构，而不是训练**（微调甚至可能有害）
2. 排行榜的 0.12 **不代表模型不行**，而是脚手架还没做好

**该论文的可靠性边界（必须说明）**：
- 非同行评审，作者署名为 "Utopia IA — Independent Research"（含 Anthropic 模型署名）
- 样本量小（n=5，能力图 n=1）
- 用的是 **Q4 量化**，竞赛用的是 **QAT W4A16**，不完全等同
- 任务类型是通用 agentic 任务（DevOps/爬虫/生物信息），不是 SWE-bench
→ **方向性参考可信，具体数字不可直接外推。**

### 论文给出的三种失败模式（对我们的 prompt 设计直接可用）

| 类型 | 表现 | 对应措施 |
| :--- | :--- | :--- |
| **A — 动作脱落** | 输出长分析但**不调用工具**；一旦发生，工具调用率从 ~80% 掉到 ~10% | **这正是 harness 的 nudge 针对的场景**。prompt 必须强调"每个回合都要发工具调用" |
| **B — 字段混淆** | 读对了文件，但**取错了字段**（如从"修饰残基"而非"自然变异"节解析） | 影响定位策略：`resolve_node_name` / `search_similar_code` 要用**精确符号** |
| **C — 数据为空时的假完成** | 在零数据上宣告成功 | prompt 必须要求"验证输出非空、测试实际通过"再提交 |

---

## 六、尚未解决 / 需要实测的问题

| 问题 | 为什么重要 | 怎么解决 |
| :--- | :--- | :--- |
| 官方评测时**是否**开了自动压缩？ | 直接决定上下文策略的松紧 | 无法从源码确定。按"没有"设计（更保守） |
| `skills/*.py` **是否会被执行**？ | 决定能否用代码实现复杂逻辑 | `code_executor` 由主办方注入，未分发。**不要依赖** |
| 31B 的实际工具调用失败率 | 决定 prompt 要多保守 | 只能实跑 |
| 多 Agent 是否真比单 Agent 好 | 架构方向 | 在代理模型上做对照实验 |
| 竞赛任务更接近 SWE-bench Verified 还是 Pro | 校准预期 | 用本地 129 任务的表现反推 |

---

## 七、行动要点（本次研究的可执行结论）

1. **上下文管理必须手动做**，靠 `include_contents: none` + `output_key` + `AgentTool`，
   不要指望框架的自动压缩。
2. **把命令纠正规则写进 prompt**，不要做成子 Agent 审核（同规则，成本低一个数量级）。
3. **多 Agent 从单 Agent 起步**，仅在代理模型上验证出增益才引入。
4. **优先做 prompt 与架构迭代**，LoRA 微调排在最后（有实证显示可能负收益）。
5. **用 12B 做代理模型**做相对比较；绝对分靠排行榜偶尔校准。
6. **校验脚本先跑通**（已完成），保证格式永不成为失分点。
