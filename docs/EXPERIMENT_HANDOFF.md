# Gemma 4 实验交接计划

更新：2026-09-28。本文是待执行实验协议，不把计划中的运行写成完成结果。目标是在每天一次 Kaggle 提交的节奏下，用同款量化 Gemma 的真实轨迹决定是否改变架构，并优先减少模型的工具选择、重复阅读和机械操作。

## 1. 接手契约与当前起点

- D0 是原样复现 Roman 公开报告为 0.12 的包。冻结 ZIP SHA-256：`f3534769cd8c7761b8ae83722b0f2fd381c0349587a10e84bd63e0554a4a7aa4`。0.12 是作者公开结果，不是我们已经复现的分数。已提交 ID `56641493`（2026-09-28 13:01:54 UTC），交接时状态 `PENDING`；后续状态和实际分数以 `analysis/2026-09-28-public-baselines/submissions.json` 为准。不要重复提交 D0。
- D0 不顺手修改 prompt、预算、思考参数、工具或文件排列；保存原始 ZIP，直接提交相同字节。后续从解压的独立副本构建候选，原件始终保留。
- 当前本机是 M4、24 GiB，没有可用 GPU 推理 endpoint。既有本地检索实验和 scripted-model 回放不属于真实 Gemma 解题率实验。
- 每天安排一次正式 submission，未达到质量门槛则延后实验候选，不为了凑次数上传盲改版本；同一天不以多次 leaderboard 试探参数。错误重试须先确认没有接受成功，避免重复消耗名额。
- 执行者交付：不可变候选 ZIP 与 SHA、唯一 run ID、配置和数据清单、真实轨迹索引、逐题配对结果、失败分类、次日唯一建议。决策者据这些材料选择是否推进下一阶段。
- 本文不授权执行者自行购买算力、扩大预算或推送原始数据；GPU 提供方、费用上限、最长租用时间、关闭责任人应由项目负责人先绑定。本文本身没有启动 GPU。

## 2. 规则边界与证据来源

以线上规则和主办方最新说明为准，分发库只证明接口能力。开始新一轮前记录所用官方 notebook revision 和下载时间；只有规则变化才重新核查，避免每次重复盘点。

- [官方 Getting Started](https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent)：使用 `gemma-4-31b-it-qat-w4a16-ct`，官方示例模型 revision 为 Kaggle `/2`，32,768 context，`gemma4` tool/reasoning parser。
- [主办方讨论 743964](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964)：截至 2026-09-28，不支持 parallel calls；LoRA 问题昨日修复；使用 Gemma 自身生成训练数据的方向得到允许，其他模型仍待澄清；12 小时 overrun 问题尚未修复。不得把“将修复”当成已经支持。
- [主办方讨论 743063](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743063)：评分任务顺序运行，提交 `eval_config.yaml` 读取 `timeout_seconds`、`max_tool_calls`、`max_time_minutes`、`max_turns`。总推理预算包含环境准备时间，不能用本地 CLI 的 concurrency 改变线上调度。
- [主办方讨论 743573](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743573)：自定义 Python 工具通过 skill script 接入。当前 swegemma 未向 compiler 提供 callback registry，不能靠包内 callback 在第一轮前自动注入上下文。
- 后续多 Agent 试验只使用顺序执行，不调用 ParallelAgent，不依赖并行模型请求。LoRA 放到独立阶段，先做加载和单题运行，不和架构改动捆绑。

本地核对入口：`vendor/src/swegemma-0.2.7/swegemma/cli.py`、`config.py`、`harness/agent_runner.py`，以及 `vendor/src/adk_submission-0.2.11/adk_submission/schema.py`。提交允许 `.yaml .yml .md .txt .py .json .safetensors`，解压总量 3 GiB；skill 内脚本可封装确定性检索、精确编辑和验证，不能重写主办方 harness。

## 3. 数据分区与泄露防护

现有分区：train 原始 82 个任务（其中 81 个纳入现有 Python 文件检索 eligible 指标），validation 33 个，external 14 个，共 129 个。Agent 解题率评估必须覆盖完整的 82/33/14 分区，不能排除新增文件等不适用检索指标的任务。它们已经被观察或分析过，统称开发/验证/跨仓库诊断集，**不能称盲测集**。分别报告原始任务数与检索eligible数；任何缺失/未运行任务都列出原因，不能仅挑可定位现有 Python 文件的任务计算 Agent 总解题率。

接手时绑定这三个集合的实际 ID 清单及 SHA，保持同一 repo/base_commit 组不跨分区；发现重复组跨分区时先修订清单并重新冻结，不能带着泄露继续比较。新增真正未见数据时另起独立版本，不混入既有验证结果。禁止按排行榜反馈移动任务。

推理可见内容仅为 issue、允许的 hints、初始仓库及正式可用资源。`patch`、`test_patch`、oracle 定位、参考修复后的源码、失败/通过测试答案只交给评估端。候选包内禁止任务 ID→路径/答案表，检索索引只能来自该题初始源码。保存初始 snapshot SHA；不要把参考补丁应用到后续 Agent 工作区。

评分流程分离：A 从干净 snapshot 运行 Agent 并封存 patch；B 另起干净环境，按官方 verifier 应用 Agent patch 和评估测试。gold 文件、评估输出、完整任务 JSONL 不进入 Agent 可访问挂载或技能资源。优先使用隔离容器；若用官方 subprocess 路径，必须先证实主机上的 gold 路径不会暴露给 Agent。不能仅凭提示语要求模型不读取。

## 4. 分阶段实验：固定问题后再扩大

| 阶段 | 唯一问题 | 执行内容 | 升级门槛 |
|---|---|---|---|
| D0 | 公开包能否在本账号复现 | 原始 ZIP 每字节不变提交；登记状态、资源错误和真实分数 | 已返回结果；即使为零也先分类，不直接解释为架构差 |
| E0 | 本地 GPU 测量链路是否可信 | 官方模型启动、1 题通路、3 题不同规模、12 题分层 pilot；保存实际事件和 verifier 结果 | 无字段缺失/数据泄露；模型、工具调用和测试确实执行；资源 profile 可复现 |
| E1 | 确定性工具是否减少无效工作 | A0 受控 single coder 与 A1 同一 coder 加统一 packet 工具，先 train、再冻结到 validation | 达到下文效果与资源门槛，不能只看文件 Hit@k |
| E2 | 专业 localizer 是否值得额外模型调用 | 主要对照 A1 与 A3，使用相同初始 packet；另以 A2 原生搜索 localizer 对照 A3 的检索工具 | 额外调用带来真实 solved 增益或相同 solved 下明确节省时间/token |
| E3 | 思考/采样预算能否进一步降本 | 只对胜出架构，单独比较 max_output/thinking/temperature；每次只动一个因素 | 实际请求与服务行为证实参数生效，解题率不明显退步 |
| E4 | 是否值得训练 LoRA | 固定胜出架构，Gemma 生成/人工标注数据按来源隔离；先训练与加载冒烟 | 规则明确、费用获批、训练/验证不混用；实际修复增益覆盖复杂度 |

架构编号必须分清：

- **R0**：Roman 原始双 Agent 公开包；仅用于 D0 原样复现与外部基准，不叫单 Agent 基线。
- **A0**：受控 single coder，使用原生文件/命令工具；按本轮统一模型、采样和预算构建，不等同于 R0。
- **A1**：A0 加确定性 packet 工具和最短固定调用约定；E1 比 A0/A1，只改变工具输入抽象。
- **A2**：coder + 使用原生搜索/读取工具的专业 localizer，顺序运行；是本地原生导航基线，不提供统一 packet。
- **A3**：coder + packet-backed 专业 localizer，顺序运行；固定入口取得与 A1 字节一致的初始 packet，再由同款 Gemma localizer 整理给 coder。工具脚本只做确定性处理，不自动调用模型，不加入未经验证的置信度路由。

E2 的主要因果问题是 A1/A3：相同检索证据是否值得增加专业子 Agent。A2/A3 回答 localizer 内部的原生导航与 packet 工具差异，不属于共同 packet 对照。所有 localizer 的模型调用、等待、阅读和输出计入共享预算，不给双 Agent 额外预算。

统一 packet 至少有 `packet_version/source_snapshot_sha/query_sha`、候选文件/符号/行号、有限原文片段、相关测试入口、截断标志和生成耗时。不把 gold 目标、参考解释或预测修复答案放进去。A1/A3 起始 packet 字节一致，新增阅读结果单独登记；A0/A2 没有该 packet。定位器更换版本时 A1/A3 一起换，并重新冻结实验，不能拿新检索的单 Agent 对旧检索的双 Agent。

架构对照阶段固定：模型 revision/量化/服务配置、初始数据、任务顺序、种子、最大输出、thinking配置、temperature/top_p、总工具/轮次/时间预算、packet 字符或 token 上限、验证方式。种子写进 YAML，并记录服务器是否实际采用；不假设 GPU 推理完全确定。D0 若无 seed，原样保留并标记 unset，架构实验另建固定 seed 基线，不能追改 D0。

## 5. GPU 交接与资源 profile

最接近比赛环境是官方 4×L4。单 A100 80 GiB 或 H100 80 GiB 可以作为较宽裕的工程备选，但这只是容量估计，必须先实测官方量化格式、parser、32k KV cache、工具调用支持及峰值显存；不能把 4bit 权重体积当作总显存需求，也不能把推理 profile 当作 LoRA 训练显存结论。

使用官方分发 wheelhouse 的锁定版本，不安装“最新版 ADK”替换它；本地基线为 swegemma 0.2.7 / adk_submission 0.2.11，GPU 端仍须记录实际版本、wheel SHA 和 vLLM/CUDA/driver。先下载官方 notebook 并固定 revision；按其服务段运行，主要参数如下（这是 notebook 的 API，不是假设有同名 CLI flags）：

```python
from pathlib import Path
import torch
from adk_submission import VllmConfig, VllmServer, discover_adapters
from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS

# 由执行者绑定 GPU 主机绝对路径；不要把下列字面占位路径直接运行。
MODEL_PATH = Path('/ABS/PATH/TO/OFFICIAL/MODEL/REVISION_2')
AGENT_DIR = Path('/ABS/PATH/TO/FROZEN/CANDIDATE')
assert MODEL_PATH.is_dir() and AGENT_DIR.is_dir()
n = torch.cuda.device_count()
assert n in (1, 2, 4), '先确认受支持 GPU 拓扑'
adapters = discover_adapters(AGENT_DIR, adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
cfg = VllmConfig(
    model=str(MODEL_PATH), host='127.0.0.1', port=8000,
    tool_call_parser='gemma4', reasoning_parser='gemma4',
    default_chat_template_kwargs={'enable_thinking': True},
    max_model_len=32768,
    dtype='bfloat16' if torch.cuda.is_bf16_supported() else 'auto',
    gpu_memory_utilization=0.90, tensor_parallel_size=n,
    enable_auto_tool_choice=True, enable_lora=True,
    max_loras=8, max_lora_rank=128, startup_timeout=1200,
)
server = VllmServer(cfg, adapter_manifest=adapters)
server.start()
print(server.base_url)
# 在同一常驻 notebook/session 内运行评估；完成后释放本次租用资源。
```

首先记录一次启动、权重加载、空闲显存、长输入单请求、真实 1/3/12 题的峰值显存、首 token 时间、输出速率和端到端耗时。CUDA OOM、parser失效、连续3次模型请求失败或产生空轨迹时立即停止批量实验并修复，不在整套任务上重复消耗。

服务 model alias 必须与请求中的模型 ID 对得上。推荐下面的 Python API 路径：它显式使用已启动 `server` 的 endpoint，并将 agent.yaml 的别名映射到该 server 的实际模型路径。CLI 是备用路径，只有服务本身已暴露比赛别名时才直接使用；仅设置 endpoint 不会自动修复模型别名。不要猜测 CLI 存在 `--served-model` 或 `--api-base`。

## 6. 已有执行入口与待绑定项

自研候选在 `candidates/v2`、`candidates/v3`、`candidates/v4`。D0第三方原prompt不进Git：运行 `"$PYTHON" scripts/fetch_public_baseline.py --output dist/roman-public` 下载并校验原ZIP，解压目录为 `dist/roman-public/bundle`；该脚本不提交。

所有命令从项目根运行。GPU主机可用相同相对目录；`PYTHON` 必须指向已安装官方依赖的解释器。本节是执行模板，不声称这些路径已经创建。先绑定：`CANDIDATE_DIR`、`CANDIDATE_ZIP`、`RUN_TASKS`、`RUN_ID`、三份 split ID 清单、`SNAPSHOTS_DIR`、费用上限，以及实际模型服务入口。`RUN_TASKS` 是评估端文件，包含 verifier 必需字段但不可挂到 Agent 沙箱。

```bash
export PYTHON="$PWD/.venv/bin/python"
export CANDIDATE_DIR="/ABS/PATH/TO/FROZEN/CANDIDATE"
export CANDIDATE_ZIP="/ABS/PATH/TO/submission.zip"
export RUN_TASKS="/ABS/PATH/TO/PRIVATE/run_tasks.jsonl"
export SNAPSHOTS_DIR="$PWD/data/snapshots"
export RUN_ID="E0-pilot-seed0-YYYYMMDD"
# endpoint 由服务启动结果绑定；凭据通过主机秘密管理注入，勿写入Git。
export LOCAL_INFERENCE_URL="http://127.0.0.1:8000/v1"
```

先运行结构检查。现有验证器使用 mock 工具注册，未提供 skill executor；通过只说明结构可编译，不能证明真实 skill 可运行、模型有工具调用能力或能解题。

```bash
"$PYTHON" scripts/validate_submission.py "$CANDIDATE_DIR"
```

以下是 swegemma 0.2.7 CLI 的真实入口。先将预算变量绑定为该候选配置中的值，所有架构共用；CLI不会自动读取提交目录的 eval_config.yaml。Docker image 必须先按官方环境准备好；不要临时猜测不存在的 image tag。首轮用 `--task-id` 绑定真实任务 ID，之后换成已冻结的 pilot JSONL。

```bash
export TOOL_LIMIT="40"
export TURN_LIMIT="64"
export TASK_MINUTES="4.5"
export COMMAND_SECONDS="60"
export SANDBOX_IMAGE="swebench-sandbox:latest"
# 上面只是受控比较的建议起点，不覆盖D0；先与本轮冻结manifest核对。
"$PYTHON" -m swegemma.cli eval \
  --tasks "$RUN_TASKS" --snapshots-dir "$SNAPSHOTS_DIR" \
  --submission-dir "$CANDIDATE_DIR" --results-dir "experiments/private/$RUN_ID" \
  --sandbox docker --image "$SANDBOX_IMAGE" --concurrency 1 \
  --max-tool-calls "$TOOL_LIMIT" --max-turns "$TURN_LIMIT" \
  --max-time-minutes "$TASK_MINUTES" --timeout-seconds "$COMMAND_SECONDS" \
  --display quiet
```

推荐执行入口：在第5节已启动 `server` 的**同一 Python notebook/session**运行以下代码；环境变量由第6节绑定到该进程，`AGENT_DIR` 必须与启动时一致。普通 Python 脚本用 `asyncio.run(evaluator.run())`；notebook用 `await evaluator.run()`，不能在已有事件循环内调用 asyncio.run。此路径不依赖 LOCAL_INFERENCE_URL，也不会被已有的 endpoint 环境变量抢先覆盖。

```python
import asyncio
import os
import litellm
from pathlib import Path
from swegemma.models.discovery import validate_single_declared_model
from swegemma.config import EvalConfig, build_submission_limits
from swegemma.evaluate import Evaluator

candidate = Path(os.environ['CANDIDATE_DIR']).resolve()
assert candidate == AGENT_DIR.resolve(), '候选需与服务启动时的adapter发现目录相同'
declared_model = validate_single_declared_model(candidate)
TARGET_MODEL_NAME = 'gemma-4-31b-it-qat-w4a16-ct'
assert declared_model == TARGET_MODEL_NAME
# 官方示例行为；记录此值，因为不支持的参数可能被丢弃。
litellm.drop_params = True
models = server.create_model_registry(
    aliases=[declared_model], model_prefix='openai/', api_key='EMPTY',
)
# 上一行适用于第5节启动的本机回环、无认证服务；受认证服务需显式绑定凭据，勿写进文件。
limits, generation = build_submission_limits()
cfg = EvalConfig(
    tasks_path=Path(os.environ['RUN_TASKS']),
    snapshots_dir=Path(os.environ['SNAPSHOTS_DIR']),
    results_dir=Path('experiments/private') / os.environ['RUN_ID'],
    submission_dir=candidate, models=models, sandbox='docker',
    image=os.environ['SANDBOX_IMAGE'], concurrency=1,
    timeout_seconds=int(os.environ['COMMAND_SECONDS']),
    max_time_minutes=float(os.environ['TASK_MINUTES']),
    max_tool_calls=int(os.environ['TOOL_LIMIT']),
    max_turns=int(os.environ['TURN_LIMIT']),
    limits=limits, generation_constraints=generation,
    adapter_manifest=adapters,
    graph_dir='data/graphs', embeddings_dir='data/embeddings',
    wheels_dir=Path('data/wheels'), display_mode='quiet',
)
evaluator = Evaluator(cfg)
result = await evaluator.run()  # notebook；普通.py改成 asyncio.run(evaluator.run())
print(result.resolved, result.total, result.resolution_rate)
```

备用 CLI 的 endpoint 已核对 `swegemma/models/registry.py:94`：优先级为显式 `api_base` → `MODEL_PROXY_URL` → `LITELLM_API_BASE` → `LOCAL_INFERENCE_URL` → `OPENAI_BASE_URL` → localhost 默认值。CLI不传api_base，所以如果前两个环境变量存在，单改 LOCAL_INFERENCE_URL 无效。启动专用shell，确认更高优先级变量未设置且服务 `/v1/models` 确实接受比赛别名后，才运行上方CLI；不要在共享shell里盲目覆盖现有配置。受认证endpoint还需通过相应API key环境变量注入凭据，地址变量本身不含认证。首题请求日志须证实目标endpoint和model ID，再扩大运行。

官方 Kaggle notebook 使用 subprocess 时，记录为另一 runtime 条件，不把 Docker/Subprocess 两套结果直接合并。LoRA 实验应使用 notebook 的 AdapterManifest + model registry + Evaluator 路径；现有 CLI 不接 adapter manifest，不能假定加一个 YAML 就自动完成服务加载。

## 7. 真实轨迹与结果契约

官方 Evaluator 已写 `results_dir/traces/trace_<instance_id>.json`。先保留原始轨迹；归一化层另存，不覆盖事件、补造思考过程或把 mock 回复混成真实输出。实际模型未公开的内部思考填 null，禁止让另一个模型“还原”。

填写仓库模板 `templates/run_manifest.json`、`templates/task_result.json` 和 `templates/daily_experiment.md`，复制到本轮私有运行目录后再填值，不覆盖模板。

每次 run 的 manifest 必须含：run_id、UTC时间、候选/ZIP/packet SHA、代码commit、模型名与 revision/权重hash、quantization/precision、GPU型号数量显存、driver/CUDA/vLLM、harness和wheel版本/hash、seed及是否生效、采样/思考/服务参数、预算、snapshot/task/split清单hash、租用小时上限。提交型 artifact 和本地测量 adapter 分开hash。

每题至少记录：

- 实际模型请求/回复事件顺序、可观测输入输出token、tool call ID、Agent名和时间戳；缺失token用null，不用字符猜成精确token。
- 每次工具的名称/参数hash、开始结束时间、duration、exit code、输出字节和截断标志；编辑前后文件hash、编辑是否匹配、产生的diff。
- reproduction/test 命令、测试错误、环境错误、运行时长；nudge内容/次数、重试/回退、termination原因（提交/预算/异常/空补丁等）。
- 最终 patch SHA、文件数/改动量、patch是否可应用、独立 verifier 的真实 resolved/pass结果及错误；Agent自己说“通过”不是通过证据。

**待实施的测量入口**：原始 trace 未必包含上述全部字段。执行者先检查3题的真实 trace schema，再编写本地事件归一化与工具计时记录器；没有现成 `--trace-schema`、`--record-tool-duration` flag。缺的原始时序字段须在本地观测适配层记录并hash，对所有架构应用相同测量逻辑，不改提交包语义，不将观测补丁上传比赛。如果无法无干扰观测，明确缺失，不通过脑补补齐。

## 8. 指标、失败分类与淘汰门槛

主指标是同题同 seed 的真实 resolved；同时报告成本：总/中位/p90时间、模型token、模型调用、工具调用、peak显存、budget终止率。Hit@1/5、packet目标覆盖只是解释性定位指标，不能代替修复得分。报告配对胜/负/同和任务清单；基础设施失败单列，但主表保留全部尝试的分母，不能删失败刷分。

失败至少分类：环境/依赖启动；模型服务/OOM/parser；定位缺失或片段截断；需求误读；编辑失败；修复不完整/回归；测试未执行或测试误判；nudge/无效循环；预算耗尽；空patch/patch应用失败；评估工具链异常。每题一个主因、可多个次因，附真实事件定位，未知保留unknown。

候选门槛是本项目预先规定的工程门槛，非统计显著性声明：

1. **通路门槛**：3题无格式/parser/skill执行故障且轨迹完整，再扩12题；遇数据泄露立即作废该批并修复隔离。
2. **train筛选**：先12题分层pilot，少量确认后扩完整82题train；只有检索指标使用其中81题eligible，Agent resolved分母始终为82。出现2个可复现原已解决任务退步、或p90时间超过基线20%且无解决数净增，暂停该分支诊断；禁止无解释扩大参数搜索。
3. **validation升级**：冻结后跑33题；默认要求净增至少2题，或解决数不低且总token/总耗时至少下降15%，同时无新增严重预算/parser故障。小样本结果用任务级配对表和区间表达不确定性；差距临界时用相同第二seed配对复验，不挪任务。
4. **external诊断**：冻结到14题，只解释跨仓库适用性，不据其逐题改权重后仍叫留出结果；出现明显崩溃先回滚候选，修复后的这一集合降为开发诊断。
5. **复杂度淘汰**：A2/A3专业localizer若增加≥15%总推理耗时而validation净增≤1题，默认不替换简洁单Agent，除非复验出现稳定收益。没有证据的抽象层和参数一律不进候选。
6. **全局时间**：线上总任务数未确认时不凭传言固定N。拿到官方N后用保守的单题setup+推理预算计算总量，目标≤9小时，给12小时上限留余量；未知N则明确无法保证。12小时耗尽仍可能整次错误，不能假设剩余题自动记零。

## 9. 候选构建、每日提交和封存

只从审核过的清单打包；不含实验数据、trace、缓存或gold。现有 `scripts/pack_submission.py` 总是生成 **tar.gz**，即使 `-o submission.zip` 也不会变ZIP，禁止那样使用。D0直接使用原ZIP，不重新压缩。后续ZIP可用下列标准库命令从已通过校验的独立目录构建：

```bash
"$PYTHON" - <<'PY'
import os, hashlib, zipfile
from pathlib import Path
root = Path(os.environ['CANDIDATE_DIR']).resolve()
out = Path(os.environ['CANDIDATE_ZIP']).resolve()
assert not out.is_relative_to(root), 'ZIP不能放在候选目录内'
assert not out.exists(), '不覆盖已冻结artifact；使用新输出路径'
files = sorted(p for p in root.rglob('*') if p.is_file())
assert files and (root / 'agent.yaml').is_file()
assert not any(p.is_symlink() for p in root.rglob('*'))
out.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, p.relative_to(root).as_posix())
with zipfile.ZipFile(out) as z:
    assert z.testzip() is None
print(out.name, out.stat().st_size, hashlib.sha256(out.read_bytes()).hexdigest())
PY
```

将ZIP解压到新的临时目录再运行现有validate脚本，核对解压文件内容hash与冻结目录一致。做一次本轮所需的真实 skill 和模型工具调用通路检查；仅结构没变且同一artifact已有有效记录时复用证据，不重复整套检查。确认提交ZIP的SHA恰等于实验胜出artifact（D0恰等于约定hash）。

正式提交命令（只由当天指定执行者执行一次）：

```bash
kaggle competitions submit -c gemma-4-developer-agent \
  -f "$CANDIDATE_ZIP" -m "Dk frozen experiment candidate"
kaggle competitions submissions -c gemma-4-developer-agent
```

以CLI回执和submission ID判断是否接收，评分完成同时检查status、errorDescription、publicScore；不能只见 COMPLETE 就当成功。提交后记录，不反复上传相同包追分。平台算力错误归基础设施类，先查主办方说明；没有轨迹证据不能解释成“Agent思考过多”。

每日记录模板：

| 字段 | 当日填写 |
|---|---|
| 日期/执行者/当前阶段 | D0或E0…，日期不等于实验必须升级 |
| 冻结假设与唯一变化 | 为什么预期改善；其余控制项SHA |
| 本地真实证据 | run ID、配对胜负、成本、失败主因、未测项 |
| 决策 | 保留/淘汰/补测/提交，负责人及理由 |
| 今日ZIP | SHA、字节数、manifest路径 |
| Kaggle | submission ID、状态、error、真实score或pending |
| 明日动作 | 一个待证伪问题，明确阶段门槛 |

## 10. Git 与私有产物边界

Git仅提交本计划、候选小型源码/YAML、脱敏manifest、聚合表及必要的无敏感短例。原始20+GB数据、模型权重、完整issue/仓库拷贝、轨迹、prompt全文、测试输出和补丁留在本地或受控私有存储；Git里记录hash与私有索引标识即可。不要因为文件小就把gold或credentials提交。推送前只审查本次明确路径，避免全量 `git add .`。

执行者结束时交回：当前不可变基线、能从干净snapshot重跑的命令与绑定路径、运行环境manifest、轨迹私有位置、结果汇总、尚未测量事项、已停止/仍运行的GPU资源。未完成的测量适配器、真实GPU运行或线上分数须明确写“待执行”，不得以本地静态校验替代。
