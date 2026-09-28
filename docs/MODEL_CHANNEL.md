> **历史分析（保留原文，2026-09-28 已有更正）。** 本文中的提交限制、预算、评分和运行能力判断可能已过期；执行前以 [当前研究状态](../docs/RESEARCH_STATUS.md) 与 [实验交接计划](../docs/EXPERIMENT_HANDOFF.md) 为准。skill Python 可提交、外层 scorer 读取四个 eval_config 字段、模拟回放不是模型能力实测。

# 模型与环境通道

## 一、评测用的是哪个模型

**默认基座：`gemma-4-31b-it-qat-w4a16-ct`**（官方 starter kit 用的就是它）

- `qat-w4a16` = Quantization-Aware Training，权重 INT4、激活 INT16
- 全家族 4 个 L4（96GB）上约占 **16–18 GB**（~4.5 GB/卡），
  给 32k KV cache 留出 ~68 GB —— 这是它被选为默认的原因
- 权重来自 **Kaggle Models `google/gemma-4`**，评测机挂载在
  `/kaggle/input/models/google/gemma-4/{transformers|Transformers}/<name>/<version>`

全部可选别名（`swegemma/models/registry.py` 注册 + `discovery.py` 的版本表）：

| 别名 | Kaggle 版本 | 说明 |
| :--- | :--- | :--- |
| `gemma-4-31b-it-qat-w4a16-ct` | v1 | **默认**，INT4 量化 |
| `gemma-4-31b-it` / `gemma-4-31b` | v1 | bf16，~54–62 GB |
| `gemma-4-27b-it` / `gemma-4-27b` | v1 | bf16 |
| `gemma-4-26b-a4b-it` / `gemma-4-26b-a4b` | v1 | MoE，~52 GB |
| `gemma-4-12b-it` / `gemma-4-12b` | **v2** | 最轻的实用选项 |
| `gemma-4-9b-it` / `gemma-4-9b` | v1 | |
| `gemma-4-e4b-it` / `gemma-4-e4b` | v1 | 小模型 |
| `gemma-4-e2b-it` / `gemma-4-e2b` | v1 | 最小 |
| `diffusiongemma-26b-a4b-it` | v1 | 离散扩散生成 |

> 注意 `gemma-4-12b-it` 的版本是 **2**，其余多为 **1**。写错版本号会导致挂载路径找不到。

## 二、模型特性（从配置与数据推断，非模型卡）

官方 Kaggle 模型卡页面是 JS 渲染的，抓不到正文；联网资料也很少。
以下是**从评测配置反推**的确定结论：

1. **原生支持工具调用**：vLLM 启动参数 `tool_call_parser='gemma4'`
   —— 说明 Gemma 4 有专用的 tool-call 语法，不是通用 hermes 模板。
2. **原生支持思考/推理**：`reasoning_parser='gemma4'`，且有
   `default_chat_template_kwargs={"enable_thinking": ...}` 与 `reasoning_effort`。
3. **思考强度可调**：`reasoning_effort` 接受 `low` / `medium` / `high`
   （由 `thinking_level` 翻译而来）。
4. **上下文**：评测侧 `max_model_len=32768`（vLLM 硬顶）。
   注意这**小于**模型自身能力——12B 的模型卡标称 256k 上下文，但评测只给 32k。
5. **多模态**：Gemma 4 家族是文本/图像/视频（小模型含音频），
   但评测用 `limit_mm_per_prompt` 可以限制，且任务全是代码文本。
6. **许可证**：Gemma 4 12B 为 Apache 2.0 开放权重（联网资料）。

⚠️ **诚实边界**：我无法访问模型卡正文，也没有该模型的实际推理经验。
关于"它在长上下文代码任务上的实际表现""工具调用失败率""是否容易把 tool call 写断"
这类问题，**只能通过实跑得到结论**，不能靠推断。

## 三、是否存在"可付费的评测环境模型通道"

分三种情况说清楚：

### (a) Kaggle Model Proxy —— 端点是公开的，但 key 不对外

代码里读的变量（`swegemma/models/registry.py:92-110`）：

```
MODEL_PROXY_URL  >  LITELLM_API_BASE  >  LOCAL_INFERENCE_URL  >  OPENAI_BASE_URL
MODEL_PROXY_API_KEY > LITELLM_API_KEY > LOCAL_API_KEY > OPENAI_API_KEY > "EMPTY"
```

官方 `kaggle-benchmarks` 仓库的 `local_development.md` 给出了实际端点：

```env
MODEL_PROXY_URL=https://mp-staging.kaggle.net/models/openapi
MODEL_PROXY_API_KEY={your_token}
```

但该文档**明确写着 "Local Development is for internal team (kaggle) only"**，
且需要向 Kaggle 申领 token。**没有公开的自助付费入口。**

> 这解释了为什么 `normalize_api_endpoint()` 会专门处理
> `/models` → `/models/openapi` 的改写——那是 Kaggle 内部代理的路径约定。

### (b) 自建 —— 完全可行，且是推荐路径

因为 Gemma 4 是**开放权重**，我们可以自己托起来：

- **Kaggle Notebook 免费 GPU**：T4×2（32GB）或 L4。
  - 31B W4 量化约需 16–18 GB → **单卡 24GB 可跑**
  - bf16 的 31B 需 54–62 GB → 免费档跑不动
  - 12B / e4b 在 T4×2 上很宽裕 ← **推荐的代理模型**
- **租云 GPU**：A100 40G / L40S 48G 级别即可跑 W4 的 31B，
  按小时计费（量级 $1–2/hr）。想拿"接近官方"的基线可以这么做，但成本要自己权衡。
- **接任意 OpenAI 兼容端点**：`--models-yaml` 可以为别名单独指定 `path` / `api_base` / `api_key`。

### (c) 精确复现官方评测机 —— 做不到

4×L4 + `tensor_parallel_size=4` + 官方 metric 壳都是 Kaggle 侧未分发的东西。
**我们永远拿不到与排行榜完全一致的绝对分。**

→ 所以正确的心态是：**用代理模型做相对比较**（A 提示词 vs B 提示词），
绝对分靠偶尔提交到排行榜来校准。

## 四、模型通道的三种注入方式（按侵入性排序）

### 1. 环境变量（零代码改动）

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8000/v1   # 或任何兼容端点
export OPENAI_API_KEY=EMPTY
```

⚠️ **坑**：`normalize_api_endpoint()` 会把"含 `/models` 且不以 `/v1`、`/openapi`、`/genai`
结尾"的 URL 强行改写成 `/openapi`。
→ **让你的 URL 以 `/v1` 结尾**即可绕开这个改写。

优先级：`MODEL_PROXY_URL` > `LITELLM_API_BASE` > `LOCAL_INFERENCE_URL` > `OPENAI_BASE_URL`。
也支持项目根目录的 `.env`（`load_dotenv(override=False)`，不覆盖已有环境变量）。

### 2. `--models-yaml`（CLI 参数）

```bash
swegemma eval ... --models-yaml my_models.yaml
```

```yaml
models:
  my-surrogate:
    path: openai/gemma-4-12b-it      # 送进请求的 model 字段
    api_base: http://127.0.0.1:8000/v1
    api_key: EMPTY
```

⚠️ 内置别名先注册、YAML 后注册。**避免复用内置别名**（如 `gemma-4-12b-it`），
用一个新别名（`my-surrogate`）并在 `agent.yaml` 里引用它更稳妥。

### 3. 编程式构造 `EvalConfig`（最灵活）

```python
from swegemma.config import EvalConfig
from swegemma.models.registry import setup_gemma_model_registry
from swegemma.evaluate import Evaluator

models = setup_gemma_model_registry(api_base="http://127.0.0.1:8000/v1", api_key="EMPTY")
cfg = EvalConfig(
    tasks_path=..., snapshots_dir=..., results_dir=..., submission_dir=...,
    models=models,
    sandbox="subprocess",        # ← 不需要 Docker
    graph_dir="data/graphs", embeddings_dir="data/embeddings",
    max_time_minutes=30, max_tool_calls=50,
)
Evaluator(cfg).run()
```

## 五、单模型规则的实际含义

`validate_single_declared_model()` 会遍历根配置、所有 `sub_agents[*].config_path`、
所有 `tools[*].agent_tool.config_path`，以及目录下的独立 agent YAML，
把所有 `model` 字段归一化（剥掉 `openai/` `google/` `hosted_vllm/` `custom/` 前缀）后去重。

- 0 个 → 报错
- ≥2 个不同模型 → 报错

**但 `adapter` 可以各不相同**——所以"一个基座 + 多个专用 LoRA"是允许的架构。
（前提是你真的训练了多套 LoRA，见 `docs/PLAN.md` 的 L3。）
