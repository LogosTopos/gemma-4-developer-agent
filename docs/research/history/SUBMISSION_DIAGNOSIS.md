> 历史时点记录：保留当时状态与证据，不代表当前提交状态。最新结论见 [研究状态](../../RESEARCH_STATUS.md)，最新提交见 [登记表](../../../analysis/2026-09-28-public-baselines/submissions.json)。2026-09-28 主办方已确认应用 LoRA 加载修复。

# 提交状态与算力错误核查（2026-09-26）

上一轮新生成的 `gemma4_experiment_pack.zip` 是研究数据包，不是 Kaggle submission，不应直接上传。原项目 `dist/submission.zip` 是 2026-09-24 的旧提交包；本次没有修改它，也没有再次提交。

## 已核实的证据

- Kaggle API 的唯一可见提交为 `56521006`，2026-09-24 12:17:41 UTC（北京时间 20:17:41），文件 `submission.zip`。
- 状态字段为 `SubmissionStatus.COMPLETE`，但 `error_description` 为：`Your notebook has requested more CPU, GPU or TPU resources than are available.`
- publicScore/privateScore 均为空。COMPLETE 仅说明处理结束，不能据此称为评分成功。原始字段保存在同目录 `submission_status_evidence.json`。
- 本地旧 ZIP 为 4,568 字节，解压后文件内容 6,846 字节；SHA-256 为 `4da508e3a04019b33612705f43f8b271ac74182c846e3faf5b3e16b16292a4a2`。未下载历史提交文件做二进制比对，不能断言远端历史字节与当前本地 ZIP 完全相同。
- 旧 ZIP 重新解压后通过本地目录校验、单模型规则和 ADK Agent 编译。校验使用工具占位函数，没有加载真实模型、请求 GPU 或执行完整官方评分。
- 项目原有 e2e 脚本使用 mock LLM，其结果为一个任务、零个解决，不能作为真实 Gemma 推理成功的证据。

## 报错的含义与目前不能确认的部分

[Kaggle 官方错误说明](https://www.kaggle.com/code-competition-debugging)把 `Notebook Exceeded Allowed Compute` 定义为重跑时违反执行环境或比赛资源约束；`Notebook Timeout` 是单独的错误类别。不能把前者直接翻译成“推理时间太长”。

这次 API 给出的更具体提示是 CPU/GPU/TPU 请求超过可用资源。它支持优先核对加速器数量/类型、评测作业资源配置与平台供应，但不能单凭该句确定资源分配失败的具体阶段，也不能证明一定由主办方导致。当前缺少失败作业的详细启动/运行日志。

旧 ZIP 仅含 agent.yaml、提示词、生成配置和子 Agent 配置，没有 Notebook 硬件设置、基础模型权重或 20 多 GB 本地数据。包小只证明没有上传大文件，不能保证模型和评测的资源需求小。

## 最新说明纠正了旧分析

通过 Kaggle CLI 下载的最新 HARNESS_README.md 说明：

1. 外层 `scripts/inference.py` 会读取 `eval_config.yaml` 中的 `evaluation:` 配置。
2. 比赛提交只允许 `gemma-4-31b-it-qat-w4a16-ct`；其他注册模型别名用于本地评估。不能擅自换 9B 来规避本次错误。
3. 官方描述的评测服务器为 4×L4，外层推理入口控制 vLLM 的配置。

旧目录“eval_config 不生效”的分析只检索了分发 wheel，漏掉外层脚本。最新公开文件清单共 524 项，不包含 `scripts/inference.py`，直接下载该路径返回 404。所以这里关于外层配置读取与 GPU 的依据是最新官方说明，未直接验证服务端入口实现。

## 建议的解决顺序

**先用一个低预算诊断提交确认云端链路。** 它应保留指定基础模型、采用单 Agent、移除 locator 和非必要图工具、缩短输出并关闭思考，不装入研究数据。可从官方样例级别预算起步，例如：

```yaml
evaluation:
  timeout_seconds: 30
  max_tool_calls: 10
  max_time_minutes: 1
  max_turns: 12
```

生成配置可先用 `max_output_tokens: 1024`、`thinking_level: NONE`、`include_thoughts: false`。这只是用于链路检查的建议起点，不是已经运行验证过的最优参数，也不是正式解题配置；过短预算会牺牲修复率。`thinking_budget: 4096` 不能当成已保证生效的推理 token 硬上限，本地模型转发桥只处理 thinking_level/include_thoughts。

明确区分两个问题：

- 如果诊断提交能完成评分，说明这一次的云端链路可运行，再逐步增加预算和模块并测量时间、内存、显存及 token。
- 如果低预算单 Agent 仍给出相同资源请求错误，尤其还未进入模型/Agent 执行阶段，应携带提交 ID、时间、完整错误和配置差异向主办方/Kaggle 核对评测作业资源设置。仅继续压缩 prompt 或降低 token 并不能改变服务端请求的 GPU 数量。
- 若详细日志证明是运行时内存/显存峰值，再针对上下文长度、生成长度、并发和缓存调整；若证明确实耗尽时限，再调整每任务预算和工具使用。不要在尚无证据时把某一原因写成定论。

本次完成的是错误取证与旧提交静态复检。尚未制作或上传上述低预算诊断 submission，也未证明错误已经修复。新实验包继续用于离线任务研究，与可提交的 Agent 配置包分开。
