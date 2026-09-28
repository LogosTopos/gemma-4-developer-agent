# 历史实验源码

这里保存 9 月 26–27 日实际使用的实验脚本。它们原先依赖 Codex 工作目录结构；不要直接在本目录执行，不要把它们作为 Agent 的工具。它们有权读取公开参考 patch 来计算离线指标。

归档脚本未重写；`analysis/research_import_manifest.json` 记录其来源和哈希。`data_pack/` 是数据审计与标签隔离工具；`v3/` 是源码语料和定位基准；`v4/` 是三轮配置选择、最终重测及工具检查。原始数据、完整代码语料、缓存和金标训练文件不进 Git。

下面的准备命令只复制脚本和已记录的指标，并把旧绝对数据路径改到当前仓库；不运行模型，不读完整快照，不覆盖原记录：

```bash
python scripts/prepare_research_workspace.py --output dist/research-replay
```

获得比赛授权并用现有下载工具准备 `data/tasks.jsonl` 和 `data/snapshots/` 后，可按以下顺序重跑最终定位比较。源码解压可能耗时，占用本地磁盘；只运行一个 worker。

```bash
python dist/research-replay/work/v3_experiments/build_corpus.py
python dist/research-replay/work/v4_experiments/final_benchmark.py --split train
python dist/research-replay/work/v4_experiments/final_benchmark.py --split validation
python dist/research-replay/work/v4_experiments/final_benchmark.py --split external_diagnostic
```

脚本依赖同版本任务与快照、现有已保存 v3 标签和 v4 选择记录；输入变更应建立新实验，不应删除断言强行通过。新结果写在 `dist/research-replay/outputs/`，不会覆盖 Git 中的历史结果。只可比较排名与覆盖；重跑耗时受设备影响，不要求与原机器相同。该流程不验证 Gemma 自主修复率。

若要重跑探索阶段，应阅读 `v4/benchmark.py` 的 `--round/--config` 和 `add_features.py` 的依赖顺序。最终算法由 `candidates/v4/` 冻结；不要把带多个实验分支的 retrieval.py 直接打包提交。脚本化模型回放的结果也不等于真实 Gemma 轨迹。
