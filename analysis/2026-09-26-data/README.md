> **历史研究数据包说明。** 本 Git 目录只发布审计与分析，下面描述的 agent/、evaluator/ 和 references/ 是原工作区产物，未随仓库分发；执行命令含原机器路径。新接手者使用 [实验交接计划](../../docs/EXPERIMENT_HANDOFF.md) 与 [历史源码恢复说明](../../scripts/research_archive/README.md)，不要按本文路径直接运行。

# Gemma 4 仓库修复实验数据包

本包依据原始 `tasks.jsonl`、仓库快照、图与向量文件以及 `swegemma-0.2.7` wheel 源码重新检查生成。日期：2026-09-26。原目录未修改。这里是任务理解与实验准备，尚未训练模型，也未测量真实模型的修复率。

## 先理解要让模型完成什么

一个任务的输入是 **问题描述 + hints（本批全为空）+ 某个版本的仓库工作树 + 工具**。模型需要反复定位代码、阅读实现与已有测试、修改文件、验证行为，然后提交工作树差异。最终产物是 patch，不是解释文字；评测检查修复后的行为，不要求逐字复制参考 patch。

主 Agent 由声明式 YAML 配置，能够读文件、执行命令、编辑文件、调用代码图工具、提交 patch；样例把代码分析子 Agent 包装成 `AgentTool`，主 Agent 可以按需调用它。评测器负责模型调用、会话与预算、仓库沙箱和判分。**评测框架已提供，并不代表当前 locator 提示词或多 Agent 方案已经有效。**

数据中的 `patch` 是参考实现，`test_patch` 是评测阶段的测试修改，不能塞进普通任务输入。评测在新的仓库环境应用候选 patch 和测试补丁；当前本地 wheel 还会验证 JUnit XML、真实通过测试和必需测试节点。仅退出码为零或输出一句“修好了”不算完成。

这些记录包含 bug 修复、边界行为改变、新功能、重构、文档代码和发布工具。没有现成的模型工具调用轨迹，因此不能直接当成 Agent 轨迹训练集。可以先用于定位与修复诊断，再由可靠的执行过程收集成功/失败轨迹。

## 原始数据核查结果

| 项目 | 结果 |
|---|---:|
| 任务 | 129 |
| FastAPI / Rich / Requests / HTTPX | 67 / 48 / 13 / 1 |
| 不同 repo + base_commit 组合 | 127 |
| 快照 / 图文件 / NPZ 文件 | 129 / 256 / 256 |
| 主要数据总大小 | 23,282,433,786 字节，约 21.68 GiB |
| 单文件参考修改 | 91 / 129 |
| 参考增删行数中位数 | 12 行 |
| 参考增删不超过 20 行 | 81 / 129 |
| 简单去模板后描述不足 200 字符 | 53 / 129；只是描述长度指标，不等同于不可解 |
| 空 hints / 空参考 patch / 空 test_patch | 129 / 0 / 0 |

2026-09-26 用 Kaggle CLI 重新下载到临时目录核对：最新 `tasks.jsonl` 与本地逐字节一致，SHA-256 为 `e4b3fd60f69dbc2b9213e54eeb9636db78aefe92c1d06269d73d9f5f8f3c8ad6`。最新 `HARNESS_README.md` 已变化，本包在 `references/` 保留该版。网络文件列表仅检查第一页，未声称完整同步远端所有资产。

所有 129 个任务的图都能解析，图元数据与任务声明的 repo/commit 一致，图节点键与 NPZ 条目键一致。按任务 ID 与 commit 命名的两个别名文件逐个比对 SHA-256，一致。12 个实验样本的全部向量都为 256 维、有限、非零。未对其余 117 个样本的全部向量进行数值检查。

## 会直接影响实验的发现

1. **20 多 GB 主要是反复打包的仓库，不是 20 多 GB 独立监督数据。** 12 个抽样快照完整扫描后，其普通文件解压字节中 Git 数据占 87.0%（Git 1,465,804,284 字节，工作树 219,049,871 字节）。这个比例仅代表所选 12 个样本，不能外推为全部快照的精确比例。
2. **不要用 `git checkout task.base_commit` 重建实验。** 12 个快照的归档 HEAD 都不等于记录中的 base_commit；对 Requests 与 HTTPX 两个快照进一步检查，声明的 commit 对象不存在，而目标文件与归档 HEAD 一致。参考 patch 能应用于归档工作树。原因尚未确定，本包以实际快照 SHA-256 和工作树为实验来源，不把它宣称成已经确认的上游 commit。检查依据见 `audit/git_worktree_probe.json`。
3. **图工具不是任意自然语言检索。** 实际调用本地 `embedding_utils.embed()`：`preserve leading slashes in request URL` 找不到向量；`HTTPAdapter` 和 `request_url` 能找到。源码是精确键/后缀匹配，短名称可能重名，优先完整限定符。全批图中未发现独立的 `async def` 定义节点；异步逻辑仍需源码搜索。
4. **现有 locator 存在配置与提示词不一致。** `submission/prompts/locator.md` 指示执行 grep，但 `submission/sub_agents/code_locator.yaml` 没有 `run_command`。这不能证明模型一定失败，却是应优先验证的可执行性问题。主 Agent 有该工具。不要直接增加一个可写 shell 后仍宣称 locator 是严格只读。
5. **本地说明曾落后于代码。** 最新下载说明补充了符号查找和 JUnit 判分。已经确认本地 `agent_runner.py`、`verification.py` 与本地 wheel 对应成员逐字节一致；没有验证远端最新 wheel 是否仍为同一版本。
6. **描述信息量差异很大。** `fastapi_14786` 描述直接给出 `.strip()`；`rich_3471` 只有标题与 issue 链接；`fastapi_15661` 几乎只有“自动准备发布”及 PR 模板，却要求具体 CLI/API。按此区别解释成绩。原始描述中的代码和答案提示保留，这是公开输入的一部分；没有主动抓取外链补全规格。

归档 Git 历史也会引入额外可见信息。本包 materializer 删除历史后创建新的 baseline。这是受控实验设置，与官方原样解压行为有区别；正式比赛对齐实验需要通过官方 harness 复测，不能直接把这里的局部结果当作官方成绩。

## 数据文件与隔离

- `agent/tasks_all.jsonl`：129 条模型可见输入，仅含 ID、repo、base_commit、原始 problem_statement、hints_text。
- `agent/tasks_pilot.jsonl`：12 条固定实验样本。
- `agent/pilot_retrieved_contexts.jsonl`：原问题 + 不使用答案的检索 Top-5 源码片段，带路径和行号。
- `agent/tasks_dev.jsonl`、`tasks_holdout_requests.jsonl`、`tasks_ood_httpx.jsonl`：按仓库分开的 115 / 13 / 1 条输入。
- `evaluator/labels_all.jsonl`：参考实现和 test_patch，只供评测/监督构建程序读取。
- `evaluator/oracle_file_contexts.jsonl`：按参考 patch 定位的完整目标文件。**含答案位置，是 oracle 定位诊断条件，绝不能混入普通评测输入。** 新文件任务给出目标路径但无原文件。
- `evaluator/task_inventory.jsonl`：全部任务的规模、描述特征和来源索引，含参考路径，不能挂到模型沙箱。
- `evaluator/retrieval_baseline.jsonl`：逐样本检索结果及参考路径命中情况。
- `audit/`：机器可读核查与实际执行记录。
- `CASES.md`：12 个样本分别在考察什么。

目录分开只是使用约定，不是权限隔离。**运行 Agent 时只挂载单个工作树及该任务输入；不要挂载整个原数据目录或本包根目录。** 本包未生成容器或操作系统级隔离设施。

## 已跑的实验

**A. 补丁静态适用性：** 对 12 个快照中的补丁涉及文件，分别执行 `git apply --check`。12/12 参考 patch、12/12 test_patch 通过。这只能证明能应用，不能证明测试通过或参考实现正确。

**B. 不读答案的文件检索：** 从完整快照中读取 Python 文件，用去模板后的问题文本做 BM25 风格检索；候选含库源码、既有测试和 Python 示例。Top-5 的每个片段取问题词匹配最多的 100 行窗口。参考路径只用于事后计分。

| 指标 | 结果 |
|---|---:|
| 至少命中一个目标文件，Top-1 | 2 / 11 |
| 至少命中一个目标文件，Top-5 | 5 / 11 |
| 至少命中一个目标文件，Top-10 | 7 / 11 |
| Top-5 目标文件召回率，逐任务平均 | 42.9% |

分母排除纯新增文件的 `fastapi_15661`。这是人工挑选的诊断子集和简单检索基线，不代表全部任务分布、模型能力或图工具性能。短语分词可能拆开标识符，结果也不能代表更好的精确符号搜索。

**C. 局部参考修复验证（Python 3.14.6，本机已有环境）：**

| 样本 | 修改前 | 应用参考修改后 | 范围 |
|---|---|---|---|
| requests_7315 | 1 failed | 1 passed | 应用公开 test_patch 后跑 `tests/test_adapters.py` |
| rich_3063 | 1 failed, 20 passed | 21 passed | 应用公开 test_patch 后跑 `tests/test_markup.py` |
| fastapi_14786 | 空格处理断言失败 | 4 条断言通过 | 直接加载目标函数，不经过完整 FastAPI 应用 |

前两个检查关闭了仓库 conftest 与自动插件，第三个只验证目标函数。没有启动官方 Docker、加载 Gemma 或跑官方完整评分，因此不是“模型 3/3 修复成功”。

## 如何开始下一轮实验

先跑下列命令建立一个干净的单任务工作树。`--destination` 必须尚不存在；工具不覆盖已有工作，也不会自动安装仓库依赖。

```bash
PY=/Users/topologyw/Documents/Kaggles/gemma_4/.venv/bin/python
PACK=/Users/topologyw/Documents/Codex/2026-09-26/bu-ya/outputs/gemma4_experiment_pack
"$PY" "$PACK/tools/materialize.py" \
  --task-id requests_7315 \
  --destination /Users/topologyw/Documents/Codex/2026-09-26/bu-ya/work/my_requests_7315
```

只给模型对应的 `agent/tasks_pilot.jsonl` 记录与这个工作树。本包的 `agent/` JSONL 是模型输入格式；由于不含 test_patch，**不可直接拿它当官方完整评分的 tasks 文件**。评分端可按 ID 从原始 tasks.jsonl 取标签，且必须与模型进程隔离。

建议先锁定一个实际可用的模型及同一解码、上下文、时间、工具调用预算，在同一批样本比较：

1. **定位实验：** 模型仅输出候选文件与符号，用参考路径算 Hit@k 和多文件召回；新增文件任务单独分析。
2. **修复实验：** 普通检索上下文与 oracle 文件上下文分别运行。后者提高幅度大，说明定位/上下文选择是主要瓶颈；两者都失败则继续看理解、编辑或验证能力。oracle 只是诊断，不是正式成绩。
3. **架构实验：** 同模型单 Agent 与主 Agent + locator 比较。先解决 locator 工具权限不支持提示词操作的问题；记录工具错误、定位召回、总 token、有效 patch、测试结果，而不只看最终文本。
4. **正式闭环：** 对候选 patch 用新沙箱按官方 harness 判分，分清模型失败、补丁无法应用、依赖/环境错误、测试超时。保存实际轨迹后再决定 SFT/LoRA 数据格式，不编造成功工具轨迹。

oracle 文件可能很长，送入模型前必须用该模型 tokenizer 计数；超过窗口时按函数或工具分页读取，记录相同的预算与截断规则，不应静默截断。当前提交 YAML 声明的是 `gemma-4-31b-it-qat-w4a16-ct`，本次未验证该模型的运行可用性；更换为计划实验的小模型时应记录实际模型身份。

`experiment_matrix.json` 固定了这些条件与建议记录字段，未假定模型已经可用。`splits.json` 按仓库隔离，避免同一仓库近邻版本随机落入训练与验证。本包准备阶段已查看部分 Requests/HTTPX 标签，因此称为保留仓库诊断集，不是从未接触过的盲测；HTTPX 只有一条，不足以估计泛化率。后续若用保留集反复调提示词，就应把它重新视为开发集。

可重跑的生成与核查工具：`tools/build_pack.py`（标准库）、`tools/check_graphs.py`（依赖已有 numpy）、`tools/run_smoke.py`（依赖已有 pytest 及相应库依赖）。重跑 smoke 时给一个新的工作目录，避免覆盖之前结果。`tools/validate_pack.py` 检查字段隔离、样本完整性、仓库拆分和结果证据。

官方入口：[Kaggle 竞赛页面](https://www.kaggle.com/competitions/gemma-4-developer-agent)。技术结论以本地原始文件、wheel 源码和本包实际检查结果为依据，未采用原目录既有分析中的结论作为验证证据。
