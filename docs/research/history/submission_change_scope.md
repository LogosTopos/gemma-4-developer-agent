> 历史时点记录：保留当时状态与证据，不代表当前提交状态。最新结论见 [研究状态](../../RESEARCH_STATUS.md)，最新提交见 [登记表](../../../analysis/2026-09-28-public-baselines/submissions.json)。2026-09-28 主办方已确认应用 LoRA 加载修复。

# 提交包可修改范围：供下一步决策

核对日期：2026-09-27。v4 已通过 Kaggle CLI 提交，编号 **56606835**，提交时间为北京时间 **19:08:57**。本次查询状态为 **PENDING**，尚无分数。上传 SHA256：`94badadcf5fbd57d1e350cfcb7be1e4ca3cd60ebdd284814ee4588c19a41e01b`。

以下区分三件事：比赛明确允许什么、当前分发库能实现什么、线上是否已验证生效。格式校验通过不等于所有行为获准，也不等于所有参数被推理服务执行。

## 当前包里的六个文件，都有可修改空间

| 文件/目录 | 可以改变什么 | 主要边界 |
|---|---|---|
| `agent.yaml` | 提示引用、工具选择、skill、会话内容策略、输出状态键；也可设计子 Agent 或流程 Agent | 当前配置 schema 内修改；不能任意导入 Python Agent 类或注册函数 |
| `prompts/system.md` | 工作流程、上下文组织、何时定位/修改/验证、预算提醒 | 仍须遵守任务与沙箱边界；提示词不能赋予额外权限 |
| `configs/sampling.yaml` | 采样、输出长度、停止序列、seed、思考相关配置 | 参数须在 schema 内；校验、转发与服务端实际效果需分开看 |
| `eval_config.yaml` | 单命令超时、单题时间、工具调用数、轮数 | scorer 明确只读取四个字段；不能用它重写总时限、GPU 或评分器 |
| `skills/repo-context/SKILL.md` | 工具用途、输入约定、返回格式、简短操作说明 | manifest 格式及目录名称必须有效；通用 SkillToolset 接口由框架提供 |
| `skills/repo-context/scripts/context.py` | 检索、解析、排序、片段组合、缓存、自动检查等算法；也可增加执行明确编辑操作的脚本 | 在规定沙箱内运行，消耗任务预算；不能更改评分环境或利用验证答案 |

v4 的单 Agent、六个基础工具、一个 skill、五个候选、约 6000 字符输出、4.5 分钟单题预算，都是我们自己的设计选择，并非比赛强制要求。

## 对“把复杂工作下沉到工具”的直接结论

**工具脚本不必限于只读定位。**官方说明技能脚本与 `run_command` 共用持久沙箱文件系统；因此可以在任务工作树内实现更高层的操作，例如：

- 一次查询完成定位、读取、关联查找和上下文裁剪。
- 给定文件、符号和修改内容，完成唯一性检查、精确替换、语法检查与 diff 摘要。
- 执行明确指定的复现/检查，返回退出码、关键失败信息和改动摘要。

这是根据公开接口能力作出的工程推论，不是主办方逐项批准过的专用工具清单。评分仍取实际工作树补丁；不能修改评分流程或削弱验证来制造通过。[官方工具与技能规则](https://www.kaggle.com/competitions/gemma-4-developer-agent/overview)

当前不能仅靠提交包实现的部分：

- **任意新增一个模型可见的 Python 函数名。**`tools` 的字符串项只从主办方注册表查找；自定义代码走 skill 脚本。`agent_tool` 可作为另一入口，但它包装的是模型 Agent，会增加推理成本。
- **靠 Python callback 在第一轮前自动定位。**通用 schema 虽列出回调字段，当前 swegemma 编译入口未传 callback registry；resolver 会忽略这些回调。不能把通用 ADK 能力当成已开放的比赛入口。
- **用 YAML 删除 SkillToolset 固定工具说明或预加载技能。**当前配置没有对应的 preload/tool_filter 入口。可以固定调用顺序，省掉列举与选择步骤，仍保留必要的加载与执行。

因此，继续优化工具内部的复合操作是现有接口支持的路线；彻底把模型侧入口变成一个新注册函数，则需要主办方开放接口。

## 其他允许修改的层面

**模型与 LoRA。**所有 Agent 和子 Agent 都必须使用指定的 `gemma-4-31b-it-qat-w4a16-ct`。可以提交一个或多个 PEFT LoRA 目录，由不同 Agent 引用不同 adapter；不能从通用库里存在其他模型别名推断比赛允许换基座。规范目录为 `adapters/<name>/adapter_config.json` 与 `adapter_model.safetensors`，YAML 用 `adapter: <name>` 引用。[模型规则](https://www.kaggle.com/competitions/gemma-4-developer-agent/overview)

LoRA **规则上允许，但实际生效仍需验证**。讨论区有适配器载入后被清零的具体报告，主办方回复将处理；本次未查到确认修复的后续。文档提到的最多 8 个 LoRA、rank 128 属服务配置说明，不能由我们在包中上调，也不能用本地“发现 adapter”替代线上加载验证。[LoRA 问题及答复](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743508)

**Agent 架构。**当前分发 schema 支持 LlmAgent、SequentialAgent、ParallelAgent、LoopAgent，以及子 Agent 和 Agent-as-tool。可改 `include_contents`、`output_key` 和 transfer 选项。支持这些配置不意味着多 Agent 更划算；用户要求的极简单 Agent 可以继续保留。

**采样与思考参数。**schema 包括 temperature、top_p、top_k、max_output_tokens、presence/frequency_penalty、stop_sequences、response_mime_type、seed、thinking_config。输出上限可配置在 1–32768 之间，但 32k 也是服务上下文容量，并不意味着长输入后还能生成满 32k。

需要特别注意：当前桥接代码把 `include_thoughts`/`thinking_level` 转成服务请求参数，却没有在该桥接中转发 `thinking_budget` 的数值。因此“YAML 接受了 thinking_budget”不能证明它约束了实际思考 token。v4 已通过请求回放确认 8192 输出上限和 thinking 开关；尚无真实推理证据说明各思考档位的效果。

**预算。**scorer 确认读取四项：`timeout_seconds`、`max_tool_calls`、`max_time_minutes`、`max_turns`。修改库 API 中的 concurrency、context cache 或 compaction 等同名概念，不意味着把它们加进提交 YAML 就会生效。任务顺序运行，总推理与沙箱准备共享 12 小时；单题参数不能提高该上限。[主办方预算答复](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743063)

## 当前不能修改的环境

主办方于 **2026-09-27 11:05 UTC** 明确：以官方 wheelhouse 为依赖依据，评分环境包固定，不能修改，不支持 ADK 2.x。Notebook 里自行升级包，不会使评分端接受新接口。开发训练环境与线上评分环境要分开看。[最新版本答复](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743800)

所以不能通过提交包替换评分 harness、vLLM 服务、模型加载器、预注册工具实现或已安装依赖；不能上传一个自定义 Docker 环境要求评分端采用。官方沙箱离线，不能依赖联网下载和运行时 PyPI 安装。代码修复任务要求的仓库配置变化，与修改评分平台是不同层面的操作。

## 文件与规模限制

以下取自本地官方分发的 **swegemma 0.2.7 + adk_submission 0.2.11** 实际约束，不是泛用 ADK 的默认值：

| 项目 | 当前分发限制 |
|---|---|
| 根入口 | 按比赛要求保留根目录 `agent.yaml` |
| 解压总大小 | 3 GiB 上限，含 adapters |
| 文件格式 | `.yaml .yml .md .txt .py .json .safetensors` |
| 不在当前格式白名单内 | `.sh .whl .so .npz .jsonl .bin .pt .pth` 等；不能直接照搬泛用 skill 支持格式 |
| 文件 / YAML 数量 | 10000 / 1000 |
| 单 skill / YAML 及 include 展开 | 各 50 MiB 上限 |
| Agent / 嵌套 / Loop 次数 / skill | 500 / 50 层 / 500 / 1000 |
| 提示长度 | 单 Agent 100 万字符，总计 1000 万字符 |
| 路径 | 禁止符号链接与提交目录越界 |

这些大多是安全上限，不是建议用量。几 KB 的 v4 距离上限很远。图索引、参数表等若要随包携带，可以考虑获准格式，但内容来源与使用方式仍须合规，不能用文件格式转换来规避模型或数据限制。

## 外部数据、训练与未确认事项

比赛规则允许符合可访问性、合理成本和授权要求的外部数据/工具；不允许把人工标注的官方验证/测试记录答案编入提交。每天最多一份提交，最终可选两份；获奖方案有代码、训练方法及许可交付要求。我们从公开本地任务自行划分的实验验证集，不等同于官方隐藏测试集。[比赛规则](https://www.kaggle.com/competitions/gemma-4-developer-agent/rules)

以下暂不能作肯定结论：

- **闭源教师模型蒸馏**：相关提问仍只有主办方“正在讨论”的回复。一般外部数据条款不能替代该项澄清，也不能替代教师服务本身的许可。[蒸馏讨论](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/742807)
- **另带一个神经检索/embedding 模型是否存在例外**：未发现足够明确的例外许可；不能从允许 `.safetensors` 推导出允许额外推理模型。
- **LoRA 修复是否已部署、所有采样字段是否实际生效**：需要新的主办方确认或同款服务实验。

## 可由你选择的下一步

1. **继续做工具抽象**：维持单 Agent，把“编辑前检查 → 应用修改 → 针对性验证 → diff 摘要”做成明确入口。现有接口允许，主要投入本地工程与测试。
2. **研究思考与上下文预算**：修改范围明确，但需要真实 Gemma 推理才能判断是否节省 token、是否损失正确率。
3. **进入 LoRA/SFT/RL**：提交格式明确允许，需准备训练资源，并先确认线上 adapter 确实生效；涉及闭源教师时另有未确认事项。

本次仅完成提交与边界调查，未替你实施上述任一方向。

## 实现证据索引

- `swegemma/config.py:19–73`：比赛覆写的后缀、尺寸、结构与生成约束。
- `swegemma/harness/agent_runner.py:319–344`：沙箱执行器与编译入口，未传 callback registry。
- `adk_submission/schema.py:168–325`：允许的生成字段、Agent 类与配置字段。
- `adk_submission/resolvers/tools.py:64,253`：预注册工具和 skill 构建路径。
- `adk_submission/resolvers/callbacks.py:83`：registry 缺失时的行为。
- `adk_submission/resolvers/generation.py:61`：thinking 到服务参数的映射。
- 本地 `data/HARNESS_README.md` 第 2、4、7、8 节：提交结构、沙箱、预算、补丁验证。文档与代码不一致时，上表按实际分发代码说明，并标明线上尚未确认处。

上述文件位于 `/Users/topologyw/Documents/Kaggles/gemma_4/vendor/src/` 相应版本目录；本次只读核对，未修改原文件。
