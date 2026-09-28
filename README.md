# Gemma 4 Developer Agent：研究、提交与实验交接

[Kaggle 比赛](https://www.kaggle.com/competitions/gemma-4-developer-agent)的框架分析、数据审计、Agent 候选、定位实验和真实推理实验计划。状态更新于 **2026-09-28**。

**当前自研最好分数为 0.06。** 今日已原样提交公开 Roman 0.12 基线进行复现，submission **56641493**，记录时仍为 PENDING。没有本地真实 Gemma 解题实验；现有 ADK 工具回放使用脚本化模型，不能作为解题率证据。

## 接手者先读

1. [研究状态与已更正结论](docs/RESEARCH_STATUS.md)：已完成什么，哪些判断仍待证据。
2. [实验交接计划](docs/EXPERIMENT_HANDOFF.md)：每天一次 submission、具体 GPU 上的真实轨迹、架构对照及候选淘汰规则。
3. [主 Agent＋特化子 Agent 的架构研究](docs/research/2026-09-28-agent-architecture.md)：Roman、Black Cat、我们的 v1–v4，以及输入、输出、会话和执行机制。
4. [数据利用与 LoRA 准备](docs/research/2026-09-28-data-and-training.md)：129 个任务的价值、本地处理、量化格式与训练条件。
5. [公开高分对照](analysis/2026-09-28-public-baselines/comparison.md)：排行榜和公开版本的证据边界。

## 提交与进展

| 版本 | 内容 | 结果 |
|---|---|---|
| 历史 v1：`submission/` | 主 Agent＋定位子 Agent | 56521006；无分数，历史 API 提示资源不可用 |
| [v2](candidates/v2/) | 单 Agent | 56575713；0.05 |
| [v3](candidates/v3/) | 单 Agent＋定位 skill | 本地候选，未提交 |
| [v4](candidates/v4/) | 单 Agent＋紧凑上下文工具 | 56606835；0.06 |
| D0 Roman 原包复现 | 公开 coder＋analyzer 包，字节不变 | 56641493；PENDING，不能预填 0.12 |

最新查询原始字段见 [submissions.json](analysis/2026-09-28-public-baselines/submissions.json)。状态为历史快照，不会自动更新。

## 本次归档

- [数据审计](analysis/2026-09-26-data/)：规模、别名、快照与图检查、三个参考修复的有限测试回放。
- [v3/v4 定位实验](analysis/2026-09-27-localization/)：三轮配置比较、逐题派生指标、冻结选择、脚本模型回放记录。
- [历史实验源码](scripts/research_archive/)与[恢复工具](scripts/prepare_research_workspace.py)：不覆盖历史证据地重建本地实验工作区。
- [实验模板](templates/)：运行 manifest、每题结果和每日实验卡。
- [导入来源清单](analysis/research_import_manifest.json)：本轮归档文件来源与初始哈希；后续文档更新以 Git 为准。

20GB+ 原始快照、任务/参考补丁全集、模型权重、wheelhouse、源码缓存和完整运行轨迹不纳入 Git；通过官方数据入口重建。公开方案保留来源和 artifact 哈希，通过脚本下载，不将完整第三方提示词当作本项目原创重新发布。

## 复现今日公开基线

使用已配置的 Kaggle CLI，只下载，不执行 notebook、不启动模型、不提交：

```bash
python scripts/fetch_public_baseline.py --output dist/roman-public
```

脚本必须验证 SHA256 `f3534769cd8c7761b8ae83722b0f2fd381c0349587a10e84bd63e0554a4a7aa4`；若上游更新则停止，不冒充本次 D0。实际原 ZIP 在 `dist/roman-public/submission.zip`，用于阅读的解压目录为 `dist/roman-public/bundle/`。不要因运行该脚本重复提交今日实验。

## 校验与执行的区别

```bash
# 对已有候选的结构检查，不启动真实模型
python scripts/validate_submission.py candidates/v4

# 准备独立的历史检索实验工作区，不开始运行
python scripts/prepare_research_workspace.py --output dist/research-replay
```

`validate_submission.py` 使用占位工具 registry；不能替代真实 skill 执行或模型评测。早期 `scripts/pack_submission.py` 输出的是 tar.gz，即使文件名写成 .zip 也不是 ZIP；新实验按交接文档的标准库 ZIP 方法打包，勿沿用旧错误命令。D0 保留下载到的原 ZIP，不重新打包。

真实 GPU 推理、沙箱安装、轨迹采集和单变量比较的命令与条件见[交接计划](docs/EXPERIMENT_HANDOFF.md)。本机是 M4 / 24GiB，没有 GPU 服务；仓库不承诺未实测卡型必然装得下，也不自动租卡。

## 历史资料

原框架逐行分析、模型通道和初版计划继续保留，已加历史标识。曾经的“不能提交 Python”“eval_config 不生效”“已有模拟回放证明模型能修复”等说法不能作为当前结论。允许的 Python 扩展走 skill；模型、依赖和评分环境仍受比赛规则约束。主办方最新答复与代码差异均见研究状态。
