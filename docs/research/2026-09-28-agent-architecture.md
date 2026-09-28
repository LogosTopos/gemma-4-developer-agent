# Gemma 4 修复 Agent 架构研究与交接（2026-09-28）

本文记录当前研究进展、可复核结果，以及后续“主 Agent + 功能特化子 Agent”的实验接口。本文不修改提交配置，不选择新参数，不代表已完成新的 Gemma 推理实验。

目前我们有两次正常返回的比赛成绩：v2 为 **0.05**，v4 为 **0.06**。确定性定位器在本地文件定位指标上有明显进步，但这些进步没有证明真实修复率相应提高。公开高分方案提供了另一个值得验证的假设：把定位与根因分析放进独立模型上下文，主 Agent 只接收短的、可以检查的分析结果，再修改和验证代码。它仍然需要额外模型调用，且评分端目前不支持并行调用，不能将其描述成免费的并行加速。

## 1. 证据范围与阅读方法

证据按以下层次区分：

1. **我们的实际提交结果**：Kaggle 提交记录，包含提交编号和分数；有分数、无错误才算正常计分。旧 JSON 中的 PENDING 只是当时快照，不能覆盖后来的 COMPLETE 记录。
2. **下载的实际公开 ZIP**：直接检查 archive 文件列表、配置和提示词，并计算 SHA256。它比 notebook 的标题、说明或尚未运行的生成代码更接近实际可复现对象，但仍不能单独证明该 ZIP 就是作者最高分那次提交。
3. **本地官方分发源码**：`adk_submission 0.2.11`、`swegemma 0.2.7`、分发 wheel 中的 `google-adk 1.36.1`。这些支持接口与控制流结论；线上评分器若更换版本，仍需再次核对。
4. **公开 notebook 的作者陈述**：如分数、私人实验次数和失败分析，只标为作者报告，不当作我们复现的结果。
5. **我们的本地检索与脚本化模型回放**：前者只测文件定位；后者验证真实工具链可以按预设响应执行。二者都不是 Gemma 自主解题测量。

归档后的可移植路径为：我方版本在 `candidates/v2`、`candidates/v3`、`candidates/v4`，历史 v1 在 `submission/`；本地定位实验在 `analysis/2026-09-27-localization/v3` 和 `v4`；公开方案与成绩证据在 `analysis/2026-09-28-public-baselines/`。后者包含 comparison.md、leaderboard.csv、submissions.json、public_artifacts.json。不要依赖个人机器绝对路径恢复证据；用下列来源、提交编号、版本和哈希核对原始对象。

| 对象 | 标识 / SHA256 | 已确认的内容 |
|---|---|---|
| 我们 v2 | 提交 `56575713`；`fc55222df026baa6a3a7b5a6023919be0a4694b1f884a76ba729b334b6544000` | 0.05；单 Agent；四文件包 |
| 我们 v3 候选 | `00e7a959c03e3ff69f53c3497073dc53e410dbdeb8687190f529b3e5c15254c2` | 仅本地候选，未提交 |
| 我们 v4 | 提交 `56606835`；`94badadcf5fbd57d1e350cfcb7be1e4ca3cd60ebdd284814ee4588c19a41e01b` | 0.06；单 Agent + repo-context |
| Roman 公开 `submission.zip` | `f3534769cd8c7761b8ae83722b0f2fd381c0349587a10e84bd63e0554a4a7aa4` | 实际五文件；coder + analyzer；无 eval_config |
| Blackcat 公开 `anchor_submission.zip` | `18b20200ba4a42f99ecaa0c889664ead4b78848835317bc114f4e4095f759916` | 实际六文件；与 notebook 声称的 0.10 anchor 哈希相同 |

Roman 原样复现材料已经按 `D0-ROMAN-EXACT` 固定，并于 2026-09-28 13:01:54 UTC 提交，编号 **56641493**；本次交接时为 **PENDING**，没有新分数。可用 `scripts/fetch_public_baseline.py --output dist/roman-public` 下载重建；脚本要求严格匹配原 ZIP 哈希。不能把原样提交的准备/上传完成写成已经复现作者成绩。

## 2. 我们的 v1 → v2 → v3 → v4

| 版本 | 实际架构与信息入口 | 验证 / 计分状态 | 可以与不可以推断的结论 |
|---|---|---|---|
| v1 | 主 Agent 九个内置工具，加 `code_locator` AgentTool；子 Agent 为 read_file + 三个 graph 工具 | 提交 `56521006` 无分数；错误为请求的 CPU/GPU/TPU 资源不可用 | 能确认提交失败；不能据此判断解题能力或把失败归因于两个 Agent |
| v2 | 单 Agent，run/read/edit/write/status/submit 六个工具；较长工作流提示；无定位脚本 | 静态编译及脚本化模型真实工具回放通过；比赛 0.05 | 确认计分链路跑通；没有逐题轨迹来确认低分主要来自定位、推理还是预算 |
| v3 | 单 Agent + `repo-locator` skill；位置不明时由模型决定使用定位器，返回源文件及测试位置 | 仅本地候选；无比赛分数 | 定位比旧确定性文件检索改善，不等于比 v2 模型行为更好 |
| v4 | 单 Agent + 唯一导航入口 `repo-context`；工具内部完成检索、融合和材料裁剪 | 静态编译、四项针对性检查及脚本化模型回放通过；比赛 0.06 | 真实分数较 v2 高 0.01，但同时更改了提示、工具和预算，不能把差异归给定位器一项 |

### v1 的具体经验

现有 `submission/` 保存了 v1：主 Agent 拥有九个内置工具，另有 `code_locator`；子 Agent 仅拥有 `read_file`、`search_similar_code`、`get_code_neighbors`、`get_code_subgraph`。子 Agent 提示却要求执行 grep，构成工具声明与工作流程不匹配。其规定的六字段是 TARGET、LINES、SYMBOL、KIND、WHY、CHANGE，最多约 200 词。

这个失配值得后续设计避免，但没有证据说明它导致了第一次提交的平台资源错误。主办方在[失败提交重跑公告](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743683)中承认并处理过平台侧资源问题，因此不能把 v2 成功计分简单解释为“缩小 Agent 就解决了超算力”。

### 采样及预算的历史事实

所有版本都使用比赛指定的 `gemma-4-31b-it-qat-w4a16-ct`，没有 LoRA。

| 项目 | v1 文件声明 | v2 | v3 / v4 |
|---|---|---|---|
| temperature | 0.2 | 0.1 | 0.1 |
| top_p | 0.95 | 0.95 | 0.95 |
| max_output_tokens | 8192 | 3072 | 8192 |
| thinking | include=true，level=medium，budget=4096 | include=true，level=low | include=true；无 level / budget |
| 单题分钟 | 未在现有包内显式设置 | 3 | 4.5 |
| 工具调用上限 | 未在现有包内显式设置 | 24 | 40 |
| turns | 未在现有包内显式设置 | 32 | 64 |
| timeout_seconds | 未在现有包内显式设置 | 45 | 60 |

这里的“未设置”不等于无穷预算，也不能直接等同于本地 SDK 默认值；真实评分端如何注入缺省配置需独立确认。

### v4 本地定位实验的结果与边界

原始本地数据包含 FastAPI、Rich、Requests、HTTPX 共 129 题。v4 在原 FastAPI/Rich 数据中，按 repo + base_commit 固定分组划分本轮训练 82 题和验证 33 题；训练有一题不含已存在的非测试 Python 目标文件，故定位指标分母为 81。Requests/HTTPX 另作 14 题诊断。数据此前已被 v3 研究接触，不能称为全新盲测。

| 指标 | v3 | v4 |
|---|---:|---:|
| 本轮训练 Hit@5 | 61/81 | 68/81 |
| 验证 Hit@5 | 26/33 | 28/33 |
| Requests/HTTPX 诊断 Hit@5 | 14/14 | 14/14 |
| 验证耗时中位数 | 0.630 秒 | 0.637 秒 |
| 验证耗时 P95 | 0.723 秒 | 0.750 秒 |
| 验证返回字符数中位数 | 7606 | 3590 |

耗时覆盖已加载源码的索引、检索和结果构造，不包括扫描及进程启动。字符数比较使用各自默认呈现：v3 六候选，v4 最多五候选；Hit@5 则统一前五。Hit@5 只表示至少命中一个参考修改文件，不表示找齐所有目标、找对完整代码段或成功修复。

三轮共比较 19 种配置，最终保留函数/窗口与文件检索融合、精确名称/路径信号及结构软权重。额外代码检索、旧预测融合、图扩展、近重复去重均没有成为最终部署依赖。最后重新从原始源码运行，未复用筛选特征或旧预测，复现了选择结果。一次完整 FastAPI 语料的实际 skill 回放扫描 1252 个 Python 文件，工具内约 0.724 秒；该单例不能外推成 Kaggle 时间保证。

v4 主提示只有约 255 个英文词，固定先 load_skill 再运行脚本，不让模型选择检索策略。工具只读当前源码，不使用任务 ID、参考 patch 或答案映射。剩余缺口包括复杂跨文件语义、新模块、非 Python 文件和短标题任务。

## 3. Roman：实际公开 ZIP 的主 Agent + 分析 Agent

来源：[Roman 的公开 notebook](https://www.kaggle.com/code/romanrozen/gemma-eda-baseline-for-a-start-lb-top-1)。其 notebook 使用 0 起始 cell 编号：3 为配置，38 为提示词生成，43 为 bundle 写入，46 为打包。以下结构已用下载的真实 ZIP 复核。

```text
agent.yaml
configs/sampling.yaml
prompts/system.md
prompts/analyzer.md
sub_agents/code_analyzer.yaml
```

主 Agent `swe_coder` 拥有六个基础工具：run_command、read_file、edit_file、write_file、get_status、submit_patch，外加 `code_analyzer` AgentTool。子 Agent 拥有 run_command、read_file、search_similar_code、get_code_neighbors、get_code_subgraph。二者使用同一 Gemma 模型和同一采样文件：T=0.2、top_p=.95、top_k=40、max_output=8192、thinking_budget=4096、include_thoughts=false。ZIP 不含 eval_config、adapter、skill 或 Python 检索器。

主 Agent 的行为约定是：先用完整 issue 调用 analyzer；收到短报告后，再亲自读取对应位置核实；建立小复现；做小范围精确替换；编译、重跑复现并跑临近测试；最后看 diff 并提交。提示还限制安装依赖、修改测试及打包文件。这些是模型行为要求，不是全部由工具权限硬执行。

analyzer 从 issue 提取名称、错误、文件和参数，搜索并沿调用关系定位行为分歧，阅读源代码后生成最多 250 词的六字段报告。其提示允许 `git log -p -S`，还把 `search_similar_code` 当作概念检索入口；后者与我们对官方工具的实际 symbol-key 语义认识不一致。原样复现应保留这些事实；后续改进不得假装“高分包的每条提示都正确”。

notebook 的 EDA、TF-IDF、参考 patch 分析和编辑模拟没有进入 ZIP。不能把 notebook 中出现的分析算法当作评分时已安装的工具。

Roman 的公开排名/作者成绩是观察对象，但单靠当前 ZIP 或标题不能证明这个哈希产物对应哪一次最高分提交。原样复现与作者最高分之间的差距是后续需要测量的量，而不是现在可以许诺的结果。

## 4. Blackcat：已下载的 anchor 与当前 challenger 分开

来源：[Blackcat Pack Instinct notebook](https://www.kaggle.com/code/lucifer19/black-cat-swe-agent-pack-instinct)。Cell 5 定义包字典，cell 7 打包并登记哈希，cell 0/4/8 描述实验和版本。

实际下载并核对的是 **anchor_submission.zip**：六文件，比 Roman 多 `eval_config.yaml`。哈希与 notebook 写明的 anchor 哈希一致；作者将它称为 0.10 anchor。我们没有重新取得该包的真实 Gemma 成绩。

| 项目 | Blackcat anchor | notebook 当前 CHALLENGER |
|---|---|---|
| root | 九个内置工具 + code_analyzer | 同 anchor |
| analyzer | run/read/neighbors/subgraph 四工具 | 同 anchor |
| root 采样 | T=.2、top_p=.95、top_k=40、max_output=4096、include=false | max_output 改为 8192，其余上述字段相同 |
| analyzer 采样 | T=.1、top_p=.95、top_k=40、max_output=2048、include=false | 同 anchor |
| 单题分钟 / calls / turns | 5 / 40 / 100 | 8 / 100 / 150 |
| timeout_seconds | 120 | 300 |
| 计分证据 | 作者声明 0.10，实际 archive 哈希可核对 | manifest 的 challenger_score 为 None；不能沿用 anchor 成绩 |

两者都无 LoRA。CHALLENGER 由公开代码生成主 `submission.zip`；不是下载到的 anchor。本文不执行 notebook，也不把作者最好成绩归因于这份最新公开代码。

anchor 要求主 Agent 通常只调用一次 analyzer；issue 已精确给出文件和函数时可以跳过。主 Agent 只需发包含关键标识符的短 request，完整 issue 由子 Agent 提示末尾的 `{problem_description?}` 注入，具体机制见下一节。analyzer 最多约六次工具调用、最多 200 词报告，这些均为软约束。

Blackcat 的主提示明确关注工具故障：短行段读取、避免整文件塞满上下文、scratch 写 /tmp、测试日志先保存再取尾部、不要安装依赖、失败时换方法。当前 challenger 进一步要求空搜索返回明确的 NO MATCHES、避免重复同一调用、复现最多两次调用、不要为多语句生成复杂 `python3 -c`。这些可以作为工具层设计的候选需求，但作者报告的 209 次运行、19 题对照和循环现象没有在本次材料中附完整可复核逐题轨迹，不能当作我们的测量。

一个需要保留的细节：root 虽声明 `search_similar_code`，提示却禁止调用它，理由是输出过长。声明与禁用同时存在会增加模型注意力负担；这不是我们应原样推广的理想接口。

## 5. 子 Agent 到底看见什么：request、state 与共享工作树

核对对象是分发文件 `vendor/wheelhouse/google_adk-1.36.1-py3-none-any.whl` 中的 `google/adk/tools/agent_tool.py`，不能用“多 Agent 通常会共享对话”推测。

1. 没有额外 input schema 时，AgentTool 的接口只有一个字符串 `request`（约 160–178 行）。
2. 执行时创建新的 Runner 和 InMemorySessionService，并把 `args['request']` 作为新会话的用户消息（约 226–266 行）。**不自动复制主 Agent 的完整消息历史。**
3. 创建子会话前，复制父 ToolContext 的 state，过滤以 `_adk` 开头的内部键（约 251–259 行）。子会话的 state delta 会再更新父 state（约 269–272 行）。因此它不是与父方完全无共享状态的纯函数。
4. `swegemma/harness/agent_runner.py` 约 391–400 行在初始 session state 写入 `problem_description = task.problem_statement`，有非空 hints 时另存 hints。
5. 因为 state 被复制，Blackcat 的 `{problem_description?}` 可以在子 Agent 指令中展开成原始 issue。问号意味着该状态键缺失时允许空内容；换成不写入该键的 harness，子 Agent 可能只剩短 request，必须在迁移时检查。
6. 工具由同一任务 context 绑定，子 Agent 读取的是同一 sandbox 工作树，消耗共享任务预算。新的聊天上下文不等于新的 repository checkout 或独立的算力预算。

Roman 通过主 Agent 的 request 重传完整 issue；Blackcat 用 state 注入避免主 Agent 每次重写长 issue。两种方式都比“子 Agent 自然看见整个父对话”更明确。若以后加入复核 Agent，还需要显式传递已改文件、当前假设和已经执行的测试结果；不要假设它自动看到主 Agent 的全部工具输出。

## 6. `skip_summarization=true` 是控制流，不只是省摘要

Roman 与 Blackcat 的 AgentTool 都配置 `skip_summarization: true`。分发 ADK 的实际流程是：

```text
主 Agent 发起 AgentTool(request)
  → 子 Agent 在新会话中执行，返回分析文本
  → AgentTool 将 tool_context.actions.skip_summarization 设为 true
  → 对应 event.is_final_response() 返回 true
  → BaseLlmFlow 结束当前调用循环
  → 若未 submit_patch 且预算/错误状态允许，swegemma harness 发 continuation nudge
  → 主 Agent 才在后续 Runner 调用中继续修改和提交
```

证据位置：wheel 内 `agent_tool.py:212–213`、`events/event.py:83–97`、`flows/llm_flows/base_llm_flow.py:869–875`；分发源码 `swegemma/harness/agent_runner.py:653–739`。harness 的 nudge 还区分文本/工具调用被截断等情况；达到错误、预算或无进展限制时不会无限续跑。`max_nudges=3` 是连续计数，出现工具调用时可以清零，不能简单解释成整个任务最多三次续跑。

因此不能只说它“避免主模型重复总结，直接继续修复”；当前它会影响回合结束，后续继续依赖 harness。也不能说它“必然让任务到此停止”：swegemma 有继续机制。后续应观察真实轨迹中的 analyzer 返回、final event、nudge 和首次 edit，确认额外轮次与内容传递；不要在没有轨迹的情况下选 true 或 false。

## 7. 六字段分析结果的用途与约束

Roman 和 Blackcat 共用以下六个语义字段（不是强制 JSON schema）：

| 字段 | 子 Agent 应交付的证据 | 主 Agent 如何使用 |
|---|---|---|
| LOCATION | 相对路径、行段、函数/类 | 直接读取目标，避免重新遍历目录 |
| ROOT CAUSE | 当前源码如何产生所述行为，区分已观察与推断 | 判断分析是否覆盖 issue，而非照抄一个看似合理的补丁 |
| FIX PLAN | 与已有接口一致的具体改动，覆盖名称、默认值及边界条件 | 形成一次连贯实现，不需要重新拆解长分析 |
| RELATED | 必须同步检查的调用点/其它文件，或 none | 避免只改一个函数却遗漏调用方 |
| TESTS | 仓库内已有测试路径或 node，注明未执行 | 选择小验证，不把推荐测试当作已通过 |
| CONFIDENCE | high / medium / low，依据证据而不是语气 | 不确定时补一段源码或定向搜索；不是校准后的成功概率 |

六字段的价值是压缩交接内容、限制多 Agent 的沟通面。它没有证明返回行号正确、根因正确或补丁能通过隐藏测试。主 Agent 仍需检查关键源码并验证行为。对于新模块/功能，LOCATION 应指向最接近的扩展点，而不是伪造一个已经存在的目标文件。

## 8. thinking 配置的真实含义

`vendor/src/adk_submission-0.2.11/adk_submission/resolvers/generation.py:60–118` 的桥接函数读取 thinking_config，并写入 LiteLlm 的 `extra_body.chat_template_kwargs.enable_thinking`。

- `include_thoughts=False` 或 `thinking_level=none` 明确映射为 **enable_thinking=False**，并移除 reasoning_effort。
- `include_thoughts=True` 或已支持的正向 level 会启用 thinking；low/medium/high 还映射 reasoning_effort。
- 该桥接逻辑没有把 `thinking_budget` 映射成一个独立、可保证生效的 vLLM token 上限。因此 Roman 虽写 budget=4096，但 include=false 仍走关闭 thinking 分支。

按这个本地官方实现：Roman、Blackcat、Parthenos 公开配置都关闭 thinking；我们的 v2/v3/v4 开启。它是足以影响行为和时间的真实差异。不能据排行榜横向比较就断言“关闭一定更好”，也不能将 false 仅解释为“不显示思考但模型照常想”。后续若比较架构，应固定这项设置，否则无法分离架构效果。本轮仅记录，不改参数。

## 9. 后续接口设计：明确职责，保持主 Agent 简单

待研究的最小形态是一个负责写代码和提交的主 Agent，加一个只负责定位/根因分析的子 Agent；不同时引入规划、检索、审核和多候选投票等多层协调。以下是设计约束，不是已经打包的新版本：

- **主 Agent**：接收 issue，必要时调用固定 analyzer；检查其核心证据；精确修改；执行小验证；检查 diff；提交。无需选择搜索权重、图扩展深度或多个同义技能。
- **analyzer**：只做源码定位、行为解释和六字段交接；不直接编辑、提交或决定评分结果。read-only 不能只靠名称保证：若给 run_command，它仍然具备任意 shell 能力；在官方仅开放内置工具的前提下，此限制主要是提示约束。
- **确定性工具层**：可以把 v4 检索、相关材料裁剪和格式化作为 analyzer 的内部材料来源，是否比 analyzer 自己 grep 更好必须实测。不要让主 Agent 面对 repo-context、repo-locator、graph、搜索规划器等多个互相重叠的入口。
- **信息契约**：完整 issue 通过 state 注入或完整 request，二选一且明确检查；动态的当前 diff、已验证事实另外传入。返回短证据包，隐藏内部排名分数和策略选择。
- **验证复核**：暂不默认增加第二个 reviewer。只有真实失败分析显示主要瓶颈在已定位后的逻辑错误、且预算允许时，才单独验证复核角色的收益。

当前提交库不能由 YAML 任意注册自定义命名 Python 工具；字符串工具名只能从主办方 registry 解析。确定性脚本的正式接口是 skill。SkillToolset 会自动暴露若干通用工具与说明，不能通过当前提交 YAML 宣称彻底隐藏为一个新工具名。把它放在唯一 analyzer 的明确流程内，可以减少主 Agent 的选择负担，但也可能增加 analyzer 的调用开销，需要比较。

## 10. 交给后续执行者的问题与记录要求

本轮不跑新推理、不调整参数；后续执行者先按固定工件复现，再做受控比较。

1. **原样基线是否可复现？**以 Roman ZIP 的原始 SHA 固定 D0，不手动“顺便修正”提示或预算。记录真正提交的哈希、编号、错误及分数；不要只记录作者名字。
2. **信息是否完整到达子 Agent？**检查 root request 与子模型首次输入，确认 issue、hints、动态工作树事实；特别记录 state 缺失时的行为。
3. **控制流是否按预期恢复？**记录 AgentTool 返回、skip 标记、final event、nudge、主 Agent 恢复和 submit_patch；再考虑是否需要对该开关做单变量实验。
4. **定位正确是否转化为修复？**分别统计目标位置命中、第一次有效 edit、非空 patch、可运行验证、最终 resolved。只有文件命中无法解释剩余失败。
5. **额外模型调用是否值得？**记录 root/analyzer 各自模型轮数、工具调用、输入/输出 token、耗时和预算耗尽原因。单独记重复调用、长输出截断、参数错误与无进展。
6. **工具层抽象是否减负？**对照 analyzer 自己搜索与内部确定性 context 包，观察追加读取次数、错误定位传播、总时间及最终 resolved，而不只看返回字符更少。

开始架构对照时，应固定任务集、模型、thinking 开关、采样和全局预算，避免同时换架构和生成模式。这里给出控制变量原则，没有替后续执行者确定一组新参数。小幅排行榜差异需要结合逐题结果解释，不足以证明某个组件单独有因果收益。

## 11. 平台条件与仍待验证的限制

[主办方 2026-09-28 的澄清](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964)确认：当时 12 小时超时的修复尚未上线，需使用 eval_config 控制单题预算；不支持并行模型调用；LoRA 加载前一天刚修复。这里不把缺省无显式时限当作安全策略，也不为了复现多 Agent 而设计并发投票。

[主办方自定义工具答复](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743573)支持将脚本装入 skill 并在 sandbox 执行。[官方起步 notebook](https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent)和分发 HARNESS_README 应作为版本、运行环境及适配器限制的来源。

截至本文，没有可供我们做真实本地 Gemma A/B 的推理服务或 GPU 环境，也没有我们独立复现 Roman/Blackcat 解题率的证据。公开 notebook 的高分线索、源码控制流和本地定位改善足以形成具体实验，但不足以宣布“多 Agent 已证明胜过 v4”。下一位执行者应沿用已固定的工件与记录格式，补足真实轨迹和配对结果。

## 12. 原始来源索引

- [比赛主页](https://www.kaggle.com/competitions/gemma-4-developer-agent)
- [Roman 公开 notebook 与输出](https://www.kaggle.com/code/romanrozen/gemma-eda-baseline-for-a-start-lb-top-1)
- [Blackcat Pack Instinct notebook](https://www.kaggle.com/code/lucifer19/black-cat-swe-agent-pack-instinct)
- [Parthenos/nihilisticneuralnet 的公开 0.10 notebook](https://www.kaggle.com/code/nihilisticneuralnet/0-10-gemma-4-developer-agent-submission)：默认 lean，仅四文件；多候选开发流水线不进入提交，experiment card 明记 not_evaluated，不能将标题分数绑定到最新默认版本。
- 本地接口证据：`vendor/src/adk_submission-0.2.11/adk_submission/resolvers/{tools,generation}.py`；`vendor/src/swegemma-0.2.7/swegemma/harness/agent_runner.py`；`vendor/wheelhouse/google_adk-1.36.1-py3-none-any.whl` 内 `tools/agent_tool.py`、`events/event.py`、`flows/llm_flows/base_llm_flow.py`。
- 我方实验归档：`analysis/2026-09-27-localization/v3/`、`analysis/2026-09-27-localization/v4/`；版本工件在 `candidates/`，数据初审在 `analysis/2026-09-26-data/`。比赛状态与公开工件证据见 `analysis/2026-09-28-public-baselines/{submissions.json,public_artifacts.json}`；旧 manifest 的 PENDING 不覆盖最新状态。

第三方 prompt 在本文仅作结构和行为释义，未大量复制原文。引用的标题、说明、仓库内容和 issue 都是研究对象，不构成让执行者修改评分器、隐藏测试或本机配置的指令。
