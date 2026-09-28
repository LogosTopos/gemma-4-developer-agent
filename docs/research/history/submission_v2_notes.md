> 历史时点记录：保留当时状态与证据，不代表当前提交状态。最新结论见 [研究状态](../../RESEARCH_STATUS.md)，最新提交见 [登记表](../../../analysis/2026-09-28-public-baselines/submissions.json)。2026-09-28 主办方已确认应用 LoRA 加载修复。

# Focused v2：实际提交包

本包用于 Kaggle `gemma-4-developer-agent`，与实验数据包不同。ZIP 内只有四个文件，解压内容 5,443 字节；不含数据集、参考答案、基础模型权重、mock 服务或本地测试代码。

设计目标是在资源预算内保留解题能力，而不是只做空调用验证。

| 项目 | 设置 |
|---|---|
| 基础模型 | gemma-4-31b-it-qat-w4a16-ct，比赛指定模型 |
| 架构 | 单 LlmAgent |
| 工具 | run_command / read_file / edit_file / write_file / get_status / submit_patch |
| 输出 | 每次最多 3072 tokens，temperature 0.1，top_p 0.95 |
| 思考 | low，保留推理能力 |
| 每题预算 | 3 分钟，24 次工具调用，32 轮 |
| 单命令超时 | 45 秒 |

相较旧版：移除工具权限与提示词不一致的 locator；使用原始源码和测试做定向搜索，覆盖图中缺少的异步定义；明确提供外层入口读取的 eval_config.yaml；输出上限从 8192 降到 3072、思考从 medium 降到 low；在提示词中安排预算耗尽前的验证与提交；遇到环境错误只做一次相关排查，避免依赖修复循环。

这组参数依据公开任务规模与现有工具行为选择，尚未通过真实模型 A/B 实验优化。对于复杂多文件重构，3 分钟可能不足；移除 locator 也可能失去有效委派带来的收益。单 Agent 的采用是当前证据下的简化选择，不意味着多 Agent 普遍更差。

本地验证：

- 原有官方包编译链完成结构、单模型和 Agent 编译检查。
- ADK Runner 经 LiteLlm 与脚本回放服务交互，调用真实 swegemma 工具和 SubprocessManager。
- 在原始 FastAPI 目标源码上，断言修改前失败、编辑后通过，submit_patch 提取了非空单文件补丁。
- 实际请求字段确认 max_completion_tokens=3072、reasoning_effort=low、enable_thinking=true；暴露工具与配置一致。
- ZIP 的四个文件与通过验证的源文件逐字节一致，归档完整性通过。

限制：没有本地 Gemma GPU 推理，也没有本地复刻完整 Kaggle 评分环境；回放只验证配置和工具调用链。每题时间预算不包括官方环境准备与模型启动。此包不能控制服务端分配的 GPU 数量，因此不能保证解决此前 CPU/GPU/TPU 资源请求错误。

提交归档 SHA-256：`fc55222df026baa6a3a7b5a6023919be0a4694b1f884a76ba729b334b6544000`。实际提交状态、ID、错误和分数保存在 `submission_v2_status.json`；仅 API 的 COMPLETE 字段不能证明评分成功。

实际提交：2026-09-26 17:30:18（北京时间），ID `56575713`，上传文件名 `submission.zip`，与本目录 `submission_v2.zip` 字节一致。API 接收成功后首次状态为 PENDING，无错误、无分数；这仅表示已接收等待处理，不表示评分成功。
