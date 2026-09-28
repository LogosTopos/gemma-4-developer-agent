# Kaggle 高分结果与 v4 对照

查询时间：2026-09-28 20:06–20:12（北京时间）。排行榜、个人提交、公开 notebook 与输出 ZIP 均通过 Kaggle CLI 读取；没有执行第三方 notebook，没有修改或提交新版本。

## 当前成绩与分布

官方排行榜导出含 736 支队伍。Makus 排名 1，0.15，成员 alexmartinez75，2 次提交；第 2–13 名共 12 支队伍为 0.13。前四名账号的比赛公开 notebook 查询均未返回结果，不能据此推断他们使用了什么方法，也不能证明其代码在所有其他渠道均未公开。

| 分数 | 队伍数 |
|---|---:|
| 0.15 | 1 |
| 0.13 | 12 |
| 0.12 | 60 |
| 0.10 | 96 |
| 0.08 | 140 |
| 0.06 | 142 |
| 0.05 | 92 |
| 0.03 | 31 |
| 0.01 | 43 |
| 0.00 | 119 |

我们的提交 56606835（v4）为 COMPLETE、0.06；56575713（v2）为 COMPLETE、0.05。309 支队伍高于 0.06，142 支同分；这是同分组位置，不是对我们账号精确名次的认定。公开 0.12 分数是当前 0.06 的两倍，但不能直接等同于解题数翻倍。

社区根据分数截断序列推测 public 有 58 题；若该假设成立，0.05、0.06、0.12、0.15 分别约为 3、4、7、9 题。这个题数没有主办方确认，不应写成已知事实。一次分数上升也不证明净增加的题都是同一类问题，可能同时有新增通过和回归。

来源：[排行榜](https://www.kaggle.com/competitions/gemma-4-developer-agent/leaderboard)、[58 题的社区推算](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743506)。

## 可检查的公开方案

| 方案 | 分数证据 | 已检查实现 | 与 v4 的差异 |
|---|---|---|---|
| Roman Rozen | 当前队伍第 14，0.12；公开 notebook 标注 0.12 | 下载实际公开输出 submission.zip，5 文件，无 LoRA、skill 或 Python 检索脚本；coder + analyzer | 关闭 thinking；不附 eval_config；定位器返回根因、修复计划和测试位置 |
| Pathfinder | 当前作者队伍第 40，0.12；最新代码的 v2 成绩仍写 pending，v1 自报 0.08 | 公开代码默认 coder + analyzer，无 LoRA，默认不附 eval_config | 关闭 thinking；强调完整 issue、预算检查；不能将作者最高分归给当前默认版本 |
| Black Cat anchor | 当前作者队伍第 111，0.10；公开 manifest 将此分数绑定旧 anchor 哈希 | 下载 anchor_submission.zip，哈希与作者固定值一致；coder + analyzer，无 LoRA、skill | 5 分钟、40 calls、100 turns、120 秒命令；主输出 4096，关闭 thinking |
| Black Cat challenger | 作者明确写 challenger_score=None | 当前主 submission.zip 的构建代码为新候选 | 8 分钟、100 calls、150 turns、300 秒命令；不能把 0.10 归给它 |
| Parthenos / Gemminem | 当前队伍第 74，0.10；notebook 将 0.10 写为 previous_user_reported_score | 当前默认 lean 候选为单 Agent、9 内置工具、4 文件；状态 not_evaluated | 4.5 分钟、40 calls、100 turns、60 秒命令；关闭 thinking；多候选本地流水线不在 ZIP 中 |
| 我们 v4 | 官方本次提交 0.06 | 已提交单 Agent + 确定性 context skill，无 LoRA | 4.5 分钟、40 calls、64 turns、60 秒命令；主输出 8192，开启 thinking |

下载到的公开输出包并不自动等于作者取得最好成绩的参赛字节；Roman 没有获得评分提交与该 ZIP 哈希的严格绑定。Black Cat 的绑定为作者声明且哈希匹配，不是我们取得了评分端原包。

来源：[Roman](https://www.kaggle.com/code/romanrozen/gemma-eda-baseline-for-a-start-lb-top-1)、[Pathfinder](https://www.kaggle.com/code/mizeroluckygall/pathfinder-gemma-4-agent-eda-baseline)、[Black Cat](https://www.kaggle.com/code/lucifer19/black-cat-swe-agent-pack-instinct)、[Parthenos](https://www.kaggle.com/code/nihilisticneuralnet/0-10-gemma-4-developer-agent-submission)。

## 对判断影响最大的发现

1. **目前公开证据不支持“高分必须 LoRA”。**检查的这些包没有 adapter。0.15/0.13 私有方案是否训练未知。公开 notebook 的 EDA、TF-IDF 或本地多候选实验，不等于这些算法进入提交。
2. **thinking 是明确的配置差异。**Roman、Pathfinder、Black Cat、Parthenos 均设置 include_thoughts=false，我们 v4 为 true。本地 adk_submission 0.2.11 的 resolvers/generation.py 第 92–95 行将 false 转为 enable_thinking=false，不能沿用部分 notebook 所说的“模型照常思考，只是不显示”。这只证明配置如何转发，不证明关掉一定提分。
3. **高分定位输出比我们的检索片段多一层语义判断。**Roman/analyzer 输出位置、根因、修复计划、关联修改和测试。v4 工具给检索证据，根因与计划仍由主 Agent 决定。这可能值得做等预算比较，但不能单凭排行榜认定第二个 Agent 有效。
4. **不能将差距一律解释为预算不足。**Roman 未明确限额、Black Cat 新候选预算较大；但其 0.10 anchor 只有 5 分钟和 40 calls，与 v4 接近。思考开关、输出长度、命令时限、提示细节同时不同，尚未做因果隔离。
5. **同方案分数可不稳定。**讨论区一位参赛者报告直接 fork Roman 后只得 0.08，耗时 14.5 小时。没有其 ZIP 哈希、逐题结果和同版本环境，无法确认是采样、环境、版本还是实现差异。因此复制 0.12 notebook 不能视为保证得到 0.12。
6. **局部检索指标不是端到端成绩。**我们的 v4 本地 33 题 Hit@5 为 28/33，v3 为 26/33；它只衡量找到至少一个目标文件。线上 v2→v4 同时改动定位、提示、预算和思考配置，不是定位器单变量实验，也不能将 0.01 的增量单独归给定位器。

复制复现报告来源：[代表方案得分讨论](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743140)。

## 今日主办方更新

Ryan Holbrook 于 2026-09-28 10:32 UTC 回复：

- 12 小时超时处理尚未修复，应通过 eval_config.yaml 做单题预算。
- 不支持并行模型调用；多 Agent 不能据此假设并行加速。
- 昨日已应用 LoRA 加载修复。此前我们“未确认修复”的结论需要更新；仍需我们自己的加载有效性检查。
- 允许使用 gemma-4-31b 自生成数据训练；其他模型输出仍待答复。

来源：[主办方答复](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964)。

另外，有参赛者报告公开训练任务的参考补丁在官方离线环境中也可能因依赖和 Python 版本失败。目前不是主办方对隐藏集的确认，不能用来解释我们所有线上失败，也不能当作排行榜上限。[报告](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743973)

## 供决策的实验问题，不在本轮实施

| 要区分的原因 | 有辨别力的比较 | 当前缺失证据 |
|---|---|---|
| thinking 是否挤占执行预算 | 固定 v4 其他内容，只比较 thinking 开关 | 每题耗时、生成量、首次编辑时间、最终通过 |
| 找到文件后仍不会修 | 同一组任务比较实际检索上下文与正确位置上下文 | 真正 Gemma 的逐题修复结果；正确位置仅可作离线诊断 |
| 确定性定位 vs 模型定位 | 同预算更换定位入口，记录传给 coder 的内容 | 真实运行，不能以代码片段命中率代替 |
| 时间或命令限制过紧 | 先观察超时/空补丁，再只增加一项预算 | 终止原因、是否留有可用补丁 |
| 需要 LoRA 学习行为 | 先建立稳定未训练基线，再同预算对照 adapter | 加载有效性和可信轨迹 |

## 核验记录

- 排行榜导出文件名时间：2026-09-28T12:06:11 UTC；736 行。
- Roman 公开 ZIP：3277 字节，SHA256 `f3534769cd8c7761b8ae83722b0f2fd381c0349587a10e84bd63e0554a4a7aa4`。
- Black Cat anchor：4690 字节，SHA256 `18b20200ba4a42f99ecaa0c889664ead4b78848835317bc114f4e4095f759916`，与 notebook ANCHOR_SHA256 一致。
- notebook cell（从 0 起）：Roman 3/38/43/46；Pathfinder 3/25/30/34；Black Cat 5/7；Parthenos 6/14/15/16。
- 原始 CLI 输出、公开 notebook 和 ZIP 保存在本任务 work/leaderboard_20260928；用户交付的排行榜快照见同目录输出文件。
