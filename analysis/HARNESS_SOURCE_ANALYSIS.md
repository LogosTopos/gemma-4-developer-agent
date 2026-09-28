> **历史分析（保留原文，2026-09-28 已有更正）。** 本文中的提交限制、预算、评分和运行能力判断可能已过期；执行前以 [当前研究状态](../docs/RESEARCH_STATUS.md) 与 [实验交接计划](../docs/EXPERIMENT_HANDOFF.md) 为准。skill Python 可提交、外层 scorer 读取四个 eval_config 字段、模拟回放不是模型能力实测。

# swegemma 评测框架源码精读报告

> 分析对象（本地已解包 wheel，**只读分析，未修改任何文件**）：
> - `<PROJECT_ROOT>/vendor/src/swegemma-0.2.7/swegemma/`（评分引擎，0.2.7）
> - `<PROJECT_ROOT>/vendor/src/adk_submission-0.2.11/adk_submission/`（声明式 agent 编译器）
> - `<PROJECT_ROOT>/vendor/src/adk_eval_core-0.1.0/adk_eval_core/`（基础库）
> - 背景文档：`data/HARNESS_README.md`
>
> 行号引用格式：`文件:行号`（相对各自包根目录）。

---

## 0. 关键前置结论（TL;DR）

| 问题 | 结论 |
| :--- | :--- |
| **最终分数** | `resolution_rate = resolved 数 / 总任务数`，纯 0/1 平均，**无加权**（`adk_eval_core/runner/runner.py:31-36`） |
| **resolved 充要条件** | `pytest` 退出码 == 0 **且** JUnit XML 校验通过（无 failure/error、至少 1 个 passed、所有 FAIL_TO_PASS/PASS_TO_PASS 或 test_patch 推导出的测试节点都通过） |
| **本地是否存在 `metric/scoring.py`** | **不存在**。该文件是 Kaggle 侧评测入口，不在 vendor 里。vendored 代码中没有任何 `def score(` 或 `SWE_*` 环境变量 |
| **`eval_config.yaml` 会不会被读** | **不会**。全 vendor 树 grep `eval_config` 零命中；CLI 也没有 `--config` 参数 |
| **真实默认预算** | 60 分钟 / 工具调用**无限** / LLM 轮次上限 **500** / 单命令超时 **300 秒** |
| **Code Intelligence 是否有 embedding 模型** | **没有**。`search_similar_code` 只做「节点名精确/后缀查表 → 余弦相似度」，query 不是节点名就返回 `[]` |
| **subprocess 后端能否替代 docker** | **能**（代码路径完整），但**本地没有 snapshots + 没有 wheels 仓库**，跑不了真实任务 |
| **能否接远程 OpenAI 兼容 API** | **能**。开关在 `MODEL_PROXY_URL`/`LITELLM_API_BASE`/`LOCAL_INFERENCE_URL`/`OPENAI_BASE_URL` 环境变量 + CLI `--models-yaml` |

---

## 1. 评分与判定闭环

### 1.1 「评分引擎」到底在哪

任务描述里的 `metric/scoring.py` **在本地 vendor 中不存在**。`data/HARNESS_README.md:539,592` 两次提到 `swegemma.metric.score()`，但该模块属于 Kaggle 侧评测壳（competition metric wrapper），没有随 wheel 分发。

全 vendor 树搜索证据：

```
$ grep -rn "eval_config" vendor/          → 0 命中
$ grep -rn "SWE_MAX|SWE_TIMEOUT" vendor/  → 0 命中
$ grep -rn "def score" vendor/            → 仅 adk_eval_core/utils/scoring.py 的 sklearn 适配器
```

vendor 内唯一的「分数」定义来自基类：

**`adk_eval_core/runner/runner.py:20-44`**
```python
@dataclass
class EvaluationResult:
    task_results: list[TaskResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.task_results)

    @property
    def resolved(self) -> int:
        return sum(1 for r in self.task_results if r.resolved)

    @property
    def resolution_rate(self) -> float:
        return (self.resolved / self.total) if self.total > 0 else 0.0
```

`swegemma/models/task.py:198-214` 的 `EvaluationResult` 只是这个基类的 dataclass 子类，新增 `by_repo()`。

落盘时（`swegemma/results.py:131-137`）：
```python
summary_data = {
    'total_tasks': evaluation_result.total,
    'resolved': evaluation_result.resolved,
    'resolution_rate': round(evaluation_result.resolution_rate, 4),
    'by_repo': evaluation_result.by_repo(),
    'errors': sum(1 for r in evaluation_result.task_results if r.error is not None),
}
```

**结论：最终分数 = resolution rate = Σ(resolved) / N，等权，无加权、无部分分、无 latency/成本惩罚。**
（`adk_eval_core/utils/scoring.py` 里的 `make_scorer` / `score_arrays` 是通用 sklearn 适配器，与本竞赛判定无关。）

### 1.2 一个任务判定为 resolved 的充要条件

判定全部发生在 `swegemma/harness/verification.py` 的 `verify_task()`。核心是**两道门**：

**第一道门：pytest 退出码**
```python
# verification.py:505
resolved = test_res.exit_code == 0
```

**第二道门：JUnit XML 复检**（只有第一道门过了才执行，`verification.py:507-542`）
```python
if resolved:
    xml_res = await sandbox_exec(docker, eval_id, f'cat {junit_xml_path} 2>/dev/null || true')
    xml_content = xml_res.stdout or ''
    is_real_sandbox = type(docker).__name__ in {
        'ContainerManager', 'SubprocessManager', 'DockerSandbox', 'SubprocessSandbox',
    }
    stdout_text = (test_res.stdout or '').lower()
    stdout_invalid = (
        bool(re.search(r'\b0 passed\b', stdout_text))
        or 'no tests ran' in stdout_text
        or 'collected 0 items' in stdout_text
        or (stdout_text.strip() != '' and 'passed' not in stdout_text)
    )
    if xml_content.strip():
        junit_ok, junit_reason = _validate_junit_xml(
            xml_content,
            fail_to_pass=getattr(task, 'FAIL_TO_PASS', ()),
            pass_to_pass=getattr(task, 'PASS_TO_PASS', ()),
            test_patch=getattr(task, 'test_patch', ''),
        )
        if not junit_ok:
            resolved = False
            junit_error = junit_reason
        elif stdout_invalid:
            resolved = False
            junit_error = 'Pytest stdout summary indicates zero or no passing tests'
    elif is_real_sandbox or stdout_invalid or not stdout_text.strip():
        resolved = False
        junit_error = 'Missing JUnit XML report (possible premature os._exit(0))'
```

`_validate_junit_xml()`（`verification.py:144-220`）的完整判定：

```python
if not xml_content or not xml_content.strip():
    return False, 'Missing or empty JUnit XML report (possible premature exit)'
...
total_tests    = sum(int(s.attrib.get('tests', 0)) for s in suites)
total_failures = sum(int(s.attrib.get('failures', 0)) for s in suites)
total_errors   = sum(int(s.attrib.get('errors', 0)) for s in suites)
total_skipped  = sum(int(s.attrib.get('skipped', 0)) for s in suites)
passed_tests   = total_tests - total_failures - total_errors - total_skipped

if total_tests <= 0 or passed_tests <= 0:
    return False, f'No passing tests recorded in JUnit XML (total=..., passed=..., skipped=...)'
if total_failures > 0 or total_errors > 0:
    return False, f'Test failures/errors recorded in JUnit XML (failures=..., errors=...)'
```

注意 `passed_tests` 是**扣掉 skipped 的**：如果测试文件里所有用例都被 skip，`passed_tests == 0` → 直接判 0。这是防 skip-all exploit 的设计。

**required_nodes 的选取逻辑**（`verification.py:181-183`）：
```python
required_nodes = list(fail_to_pass) + list(pass_to_pass)
if not required_nodes and test_patch:
    required_nodes = _extract_test_functions_from_patch(test_patch)
```

本地 `data/tasks.jsonl` 的字段是 `['instance_id','repo','base_commit','patch','test_patch','problem_statement','hints_text','created_at']` —— **没有 `FAIL_TO_PASS` / `PASS_TO_PASS`**。所以本地跑时 `required_nodes` 100% 走 `test_patch` 推导。

实测 129 个任务（用源码里同名函数跑出来的结果）：

| 指标 | 数值 |
| :--- | :--- |
| 任务总数 | 129 |
| `test_patch` 涉及的目标测试文件数直方图 | 1 个文件:98，2:15，3:5，4:1，5:1，6:2，8:1，11:1，12:1，17:1，18:1，23:1，29:1 |
| 推导出的 required_nodes 为**空**的任务 | **1**（`rich_4070`）→ 该任务只做「全绿」检查，不校验具体节点 |
| pytest target 退化到 `.`（整仓）的任务 | 0 |
| test_patch 目标文件命中「受保护路径」判定的次数 | 282（基本全是 `test_*.py` / `tests/*.py`） |

`_extract_test_functions_from_patch()`（`verification.py:86-127`）用 4 条正则从 diff 里抓测试函数名，优先级：
1. `^+\s*(?:async\s+)?def\s+(test_\w+)\s*\(` —— **新增的** test 函数，命中就直接返回（`verification.py:90-96`）
2. 否则合并 `@@ ... @@ def test_x`（hunk header 里的函数） + ` def test_x(`（上下文行）
3. 过滤掉被删除的（`-def`）与「被删函数的前缀」（`any(r.startswith(fn) for r in removed)`）

节点匹配用 `_node_matches_requirement()`（`verification.py:130-141`）：
```python
if node_name in (req, req_short, req_base): return True
short_node = node_name.rsplit('::', 1)[-1].rsplit('.', 1)[-1]
if short_node in (req, req_short, req_base): return True
if short_node.startswith(f'{req_base}_') or short_node.startswith(f'{req_base}['): return True
if len(req_base) >= 68 and short_node.startswith(req_base): return True
return short_node.startswith(req_base) and short_node[len(req_base):].isdigit()
```
即支持 `test_foo` / `test_foo[param]` / `test_foo_1`（参数化后缀）/ 长名字前缀。JUnit testcase 的候选名集合包含 `name`、`name.split('[')[0]`、`classname::name`、`classname.name`、`classname.replace('.','/')+'.py::name'`（`verification.py:187-205`）。

### 1.3 `verify_task` 完整步骤顺序（Container B）

签名：`verify_task(docker, config, task, snapshot_path, *, base_snapshot_path, patch_path, fast_path=True, agent_patch='', agent_error=None, trace=None, start_time=0.0)`（`verification.py:223-236`）

**Step 0 — 前置短路（`verification.py:238-260`）**
若 `test_patch` 为空 且 无 `FAIL_TO_PASS` 且 无 `PASS_TO_PASS` 且 无 `test_files` 且 不是 mock repo → 直接返回 `resolved=False, test_exit_code=-1`，`error='Missing test specification (...)'`。

**Step 1 — 起沙箱**：`eval_id = await sandbox_start(docker)`（`:262`）

**Step 2 — 容器准备（顺序固定）**

| # | 调用 | 行号 |
| :-- | :--- | :--- |
| 2.1 | `setup_container_wheels(docker, eval_id, config)` | `:265` |
| 2.2 | `extract_snapshot(docker, eval_id, snapshot_path, patch_path=..., base_snapshot_path=...)` | `:268-275` |
| 2.3 | `setup_synthetic_hardware(...)`（**空实现**，`:859-861` 直接 `return`） | `:278` |
| 2.4 | `setup_git_exclude(...)` 写 `.git/info/exclude` | `:281` |
| 2.5 | `install_editable_package(...)` | `:284` |
| 2.6 | `install_test_dependencies(docker, eval_id, task.repo, fast_path=True, config=config)` | `:287-294` |
| 2.7 | `setup_workspace_test_config(docker, eval_id, repo=task.repo)` | `:297-302` |
| 2.8 | `setup_baseline_commit(docker, eval_id, 'eval_baseline')` | `:305` |

其中 `setup_baseline_commit`（`container_setup.py:575-582`）执行：
```bash
cd /workspace && git add -A && git commit -m "eval_baseline" --allow-empty -q && git tag -f _swegemma_baseline
```

**Step 3 — 应用 agent_patch（`verification.py:307-353`）**
仅当 `agent_patch.strip()` 为真。写到临时文件 → `docker.copy_to(eval_id, patch_host_path, '/tmp/')` → `apply_patch_in_container(docker, eval_id, f'/tmp/{name}')`。
- `exit_code != 0` 且 stderr 含 `Patch file not found:` → **raise `ContainerSetupError`**（会冒泡出 `verify_task`，`:560-561`）
- 其他 `exit_code != 0` → 立即返回 `resolved=False`，`error = f'Failed to apply agent patch: {err_detail}'`（`:340-351`）
- `finally` 删除宿主机临时文件

**Step 4 — 计算要重置的文件（`verification.py:355-404`）**

```python
target_test_files = (list(task.test_files) if task.test_files
                     else extract_test_files_from_patch(task.test_patch))

agent_touched_files = extract_test_files_from_patch(agent_patch)
if agent_patch.strip():
    for raw_line in agent_patch.splitlines():
        if raw_line.startswith('diff --git '):   # 抓 a/ 与 b/ 两侧路径
        elif raw_line.startswith(('--- a/', '+++ b/')):
        elif raw_line.startswith('rename from '):
    # 再叠加容器内真实 git status
    git diff --name-only HEAD ; git ls-files --others --exclude-standard

protected_agent_files = [p for p in agent_touched_files
                         if _is_protected_test_or_config_path(p)]
files_to_reset = list(dict.fromkeys(
    target_test_files + protected_agent_files + [
        'conftest.py', 'pytest.ini', 'sitecustomize.py',
        'usercustomize.py', '_swegemma_stubs.py',
    ]))
```

`_is_protected_test_or_config_path()`（`verification.py:60-83`）认定为受保护的情形：
- 文件名 ∈ `{conftest.py, pytest.ini, pyproject.toml, tox.ini, setup.cfg, .pytest.ini, sitecustomize.py, usercustomize.py, _swegemma_stubs.py}`
- 扩展名 `.pth`
- 文件名 `test_*.py` 或 `*_test.py`
- 路径目录段（小写后）与 `{tests, test, testing}` 有交集且是 `.py`

**Step 5 — test 文件重置（`verification.py:406-415`）**

```bash
cd /workspace && git checkout HEAD -- <files_to_reset...> 2>/dev/null || true
cd /workspace && git clean -f -- <files_to_reset...> 2>/dev/null || true
```
（用 `shlex.quote` 逐路径转义；两条命令都是 `|| true`，**静默失败**，即使文件本来不存在也不会报错。）

**Step 6 — 应用 test_patch（`verification.py:417-463`）**
同 Step 3 流程，用 `task.test_patch`。失败 → 返回 `resolved=False, test_exit_code=-1, error=f'Failed to apply test_patch: {err_detail}'`（**注意此处 `test_output=''`，不留输出**）。

**Step 7 — 再次刷新依赖与测试配置（`verification.py:465-480`）**
- `install_test_dependencies(... fast_path=fast_path ...)`（第二次）
- `setup_workspace_test_config(docker, eval_id, repo=task.repo, overwrite=True)`（**强制覆盖** `pytest.ini` + 注入 `conftest.py` hook）

`setup_workspace_test_config` 写入的 `pytest.ini`（`container_setup.py:891-899`）：
```ini
[pytest]
addopts = -p no:anyio
norecursedirs = .* build dist venv
python_classes = Test* *Test
python_files = test_*.py *_test.py
filterwarnings =
    ignore::DeprecationWarning
    ignore::UserWarning
```
`conftest.py` 只加一行注释头 `# Hermetic test discovery hook for SWE-gemma`（`container_setup.py:914-920`），保留原内容。

**Step 8 — 运行 pytest（`verification.py:482-503`）**

```python
pytest_targets = [p for p in target_test_files
                  if Path(p).name != 'conftest.py' and p.endswith('.py')] or target_test_files
test_files_quoted = [shlex.quote(p) for p in pytest_targets]
test_files_str = ' '.join(test_files_quoted) if test_files_quoted else '.'
junit_xml_path = f'/tmp/_swegemma_junit_{uuid.uuid4().hex[:12]}.xml'
await sandbox_exec(docker, eval_id, f'rm -f {junit_xml_path}')
pytest_cmd = (
    f'cd /workspace && PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python3 -s -m pytest {test_files_str} '
    f'--junitxml={junit_xml_path} '
    '-p no:anyio -o timeout=0 '
    '-o python_classes="Test* *Test" -q'
)
test_res = await sandbox_exec(docker, eval_id, pytest_cmd,
                              timeout=config.harness.command_timeout_seconds)
```

**逐字命令行（默认配置）：**
```
cd /workspace && PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python3 -s -m pytest <targets> --junitxml=/tmp/_swegemma_junit_<hex12>.xml -p no:anyio -o timeout=0 -o python_classes="Test* *Test" -q
```

> ⚠️ **与 `HARNESS_README.md:586-588` 的差异**：README 写的命令行含 `-o norecursedirs=".* build dist venv"`，**实际代码没有这个参数**（它只写进了 `pytest.ini`）。README 还写「iff pytest 退出码 == 0」即为 resolved，**实际还有第二道 JUnit XML 校验**。

**Step 9 — 判定 + 落盘（`verification.py:505-559`）**，见 §1.2。

**Step 10 — `finally: await sandbox_stop(docker, eval_id)`**（`:577-578`）

### 1.4 「patch 正确也判 0 分」的所有情况

| # | 触发条件 | 代码位置 | 结果 |
| :-- | :--- | :--- | :--- |
| 1 | **agent_patch 为空串** | `evaluate.py:324` 只在 `agent_error and not agent_patch` 时短路；否则 `verify_task` 收到 `agent_patch=''`，跳过 Step 3 | Container B 用**原始代码** + test_patch 跑，新测试必挂 → 0 分 |
| 2 | **agent patch 应用失败**（4-pass 全挂） | `verification.py:325-351` | `resolved=False`，`error='Failed to apply agent patch: ...'` |
| 3 | **patch 文件在容器里找不到** | `verification.py:327-330` | **raise `ContainerSetupError`** → 冒泡到 `evaluate.py` 的 worker 异常分支，整任务失败 |
| 4 | **test_patch 应用失败** | `verification.py:437-461` | 0 分（`test_exit_code=-1`） |
| 5 | `agent_error` 存在但 `agent_patch` 非空 | `evaluate.py:324` 条件不成立 → **仍然进 Phase 2** | 有机会得分（这是「超时但有 diff」的救命通道） |
| 6 | `agent_error` 存在且 `agent_patch` 为空 | `evaluate.py:324-351` | 直接返回 `resolved=False`，**根本不进 Phase 2** |
| 7 | **snapshot 文件不存在** | `evaluate.py:274-295` | `error='Snapshot file not found: ...'`，0 分 |
| 8 | **secret 里既无 test_patch 也无 FAIL_TO_PASS** | `verification.py:238-260` | 0 分（`Missing test specification`） |
| 9 | pytest 退出码 ≠ 0 | `verification.py:505` | 0 分 |
| 10 | **JUnit XML 缺失/空**（典型：agent 打桩 `os._exit(0)` 让 pytest 假成功，或 conftest 提前退出） | `verification.py:540-542` | 0 分，`Missing JUnit XML report (possible premature os._exit(0))` |
| 11 | JUnit 里 `failures>0` 或 `errors>0` | `verification.py:175-179` | 0 分 |
| 12 | JUnit 里 `total_tests<=0` 或 `passed_tests<=0`（含**全被 skip**） | `verification.py:170-174` | 0 分 |
| 13 | 任一 required node 未通过（或**同时**出现在 passed 与 failed 集合里） | `verification.py:206-218` | 0 分，`Required test node did not pass: <node>` |
| 14 | pytest stdout 出现 `0 passed` / `no tests ran` / `collected 0 items` / 有输出但不含 `passed` | `verification.py:520-526, 537-539` | 0 分 |
| 15 | agent 改了受保护的测试/conftest 文件 | `verification.py:389-415` | 改动被 `git checkout HEAD --` + `git clean -f --` **静默丢弃**；若 agent 靠改测试「过关」，实际判定用原始测试 → 0 分 |
| 16 | agent 把测试文件删了 | `extract_test_files_from_patch` 对 `deleted file mode` 不收集（`models/task.py:107-108`），但 `git clean -f` + `git checkout` 会恢复 | 恢复后照常跑，通常 0 分 |
| 17 | 沙箱内任何未捕获异常 | `verification.py:562-576` | `error=f'Evaluation error: {e}'`，0 分 |
| 18 | `--skip-agent-patch` | `evaluate.py:300-303` | 故意空 patch，用于测 baseline 必失败 |

---

## 2. 真实评测预算

### 2.1 默认值（源码权威）

**`swegemma/budget.py:14-32`** —— 逐字：
```python
@dataclass(frozen=True)
class EvaluationBudget:
    """Consumable allowances that terminate or conclude a task session when exhausted."""

    time_minutes: float | None = 60.0  # Max session wall-clock time in minutes
    tool_calls: int | None = None      # Max total tool invocations
    turns: int | None = None           # Max LLM reasoning / loop turns
    cost_usd: float | None = None      # Max monetary spend in USD
    total_tokens: int | None = None    # Max total tokens consumed


@dataclass(frozen=True)
class HarnessLimits:
    """Operational constraints that govern individual tool and sandbox execution."""

    command_timeout_seconds: int | None = 300  # Timeout for a single shell command
    max_stdout_chars: int | None = 5000        # Max characters returned per command
    max_file_lines: int | None = 150           # Max lines returned per read_file
    max_file_chars: int | None = 10000         # Max characters returned per read_file
```

**CLI 默认值（`swegemma/cli.py`）**：

| 参数 | 默认 | 行号 |
| :--- | :--- | :--- |
| `--max-time-minutes` | **60.0** | `cli.py:78-83` |
| `--max-tool-calls` | **None（无限）** | `cli.py:60-65` |
| `--max-turns` | **None（无限）** | `cli.py:66-71` |
| `--timeout-seconds` | **None**（→ 回落到 `HarnessLimits.command_timeout_seconds = 300`） | `cli.py:72-77` |
| `--concurrency` | 1 | `cli.py:108-113` |
| `--sandbox` | `docker` | `cli.py:54-59` |
| `--display` | `auto` | `cli.py:129-134` |

**内部硬编码上限**：
- **LLM 轮次上限 500**：`agent_runner.py:429-431`
  ```python
  max_llm_calls = (config.budget.turns if config.budget.turns is not None else 500)
  ```
- **Nudge 上限 3**：`agent_runner.py:499` `max_nudges = 3`
- **`build_submission_limits(max_loop_iterations=500)`** 默认：`config.py:34-36`

**运行时真实生效值（CLI 默认 + 无环境变量）**：

| 项 | 生效值 |
| :--- | :--- |
| 会话墙钟时间（仅 agent loop 计时） | 60 分钟 |
| 工具调用数 | 无限 |
| LLM 轮次 | 500 |
| 单命令超时 | 300 s |
| 命令输出截断 | 5000 字符 |
| `read_file` 上限 | 150 行 / 10000 字符 |
| Nudge 次数 | 3 |
| 并发任务 | 1 |

`SwegemmaContext.check_budget()`（`context.py:467-544`）是预算的实际执行点，返回 JSON 错误串阻断工具调用，顺序为：tool_calls → turns → cost_usd → total_tokens → time_minutes；通过后 `self.tool_calls_used += 1`（`submit_patch` 与 `get_status` 用 `count_tool_call=False` **不计数**，`tools/execution.py:40,80`）。

`run_command` 的有效超时（`tools/execution.py:22-43`）：
`min(command_timeout_seconds, max(5, int(remaining_time_seconds)))`，超时返回 `error_type: TimeoutExceeded` 且**不终止会话**。

### 2.2 环境变量覆盖

**结论：vendored `swegemma` 里没有任何 `SWE_MAX_TIME_MINUTES` / `SWE_MAX_TOOL_CALLS` / `SWE_MAX_TURNS` / `SWE_TIMEOUT_SECONDS` 的读取代码。**

证据（全树 grep `SWE_`、`SWE_MAX`、`SWE_TIMEOUT`）：**0 命中**。

`HARNESS_README.md:523-533` 的表格标题写得很明确：
> **Environment Variable Override (in `score()`)**

即这些环境变量由 **Kaggle 侧的 `metric/scoring.py`（未随包分发）** 读取，读完后以关键字参数形式传给 `EvalConfig(...)`，再经 `EvalConfig.__post_init__`（`config.py:148-193`）合并进 `budget` / `harness`。

**`swegemma` 源码里真正会被读取的环境变量**（穷举）：

| 环境变量 | 读取位置 | 作用 |
| :--- | :--- | :--- |
| `KAGGLE_EVAL_ROOT` | `submission.py:20-21` | 定位评测数据根目录 |
| `KAGGLE_SANDBOX_DIR` | `container_setup.py:24` | 找 `sandbox/setup.py` |
| `MODEL_PROXY_URL` | `models/registry.py:96` | **模型 API base（注入点①）** |
| `LITELLM_API_BASE` | `models/registry.py:97` | 同上 |
| `LOCAL_INFERENCE_URL` | `models/registry.py:98` | 同上 |
| `OPENAI_BASE_URL` | `models/registry.py:99` | **同上（最通用）** |
| `MODEL_PROXY_API_KEY` | `models/registry.py:105` | API key（注入点②） |
| `LITELLM_API_KEY` | `models/registry.py:106` | 同上 |
| `LOCAL_API_KEY` | `models/registry.py:107` | 同上 |
| `OPENAI_API_KEY` | `models/registry.py:108` | 同上 |
| `LITELLM_LOG` | `swegemma/__init__.py:65`（`setdefault("WARNING")`） | 日志噪音 |
| `.env` 文件 | `models/registry.py:14` / `cli.py:19`（`load_dotenv(override=False)`） | 本地开发便利 |

`setup_gemma_model_registry()`（`models/registry.py:94-110`）逐字：
```python
raw_endpoint = (
    api_base
    or os.environ.get('MODEL_PROXY_URL')
    or os.environ.get('LITELLM_API_BASE')
    or os.environ.get('LOCAL_INFERENCE_URL')
    or os.environ.get('OPENAI_BASE_URL')
    or 'http://localhost:8000/v1'
)
endpoint = normalize_api_endpoint(raw_endpoint)
key = (
    api_key
    or os.environ.get('MODEL_PROXY_API_KEY')
    or os.environ.get('LITELLM_API_KEY')
    or os.environ.get('LOCAL_API_KEY')
    or os.environ.get('OPENAI_API_KEY')
    or 'EMPTY'
)
```

### 2.3 `eval_config.yaml` 到底会不会被读？

样例文件 `<PROJECT_ROOT>/data/sample_submission/eval_config.yaml` 内容：
```yaml
# Optional participant evaluation configuration for Stage 1 inference.
# Controls per-task execution budgets and sandbox command timeouts.
evaluation:
  timeout_seconds: 60
  max_tool_calls: 10
  max_time_minutes: 1
  max_turns: 50
```

**明确结论：**

| 问题 | 答案 |
| :--- | :--- |
| swegemma 会读它吗？ | **不会**。`grep -rn "eval_config" vendor/` → **0 命中** |
| CLI 有 `--config` 参数吗？ | **没有**。`cli.py` 的 `eval_parser.add_argument` 共 19 处，无一处读 YAML 配置 |
| 谁会读？ | Kaggle 侧评测壳 `metric/scoring.py`（**不在本地 vendor 中**）。它读 `evaluation:` 段，再把 `timeout_seconds / max_tool_calls / max_time_minutes / max_turns` 作为关键字参数传进 `EvalConfig(...)` |
| 本地优先级如何？ | 若 Kaggle 壳读了它：`EvalConfig` 的 flat kwargs > `budget`/`harness` 对象默认值（`config.py:148-193`）。CLI 直接传 `max_time_minutes` 等，所以 CLI 显式值与配置文件是**同一条通道** |
| 本地 `swegemma eval` 跑会怎样？ | **完全忽略这个文件**。默认就是 60 分钟 / 无限工具 / 500 轮 / 300 s 命令超时 |

> ⚠️ **实战含义**：`eval_config.yaml` 里的 `max_tool_calls: 10` 和 `max_time_minutes: 1` **不是本地可复现的预算**。样例文件里的极紧预算是给 Stage-1 推理用的。本地自己跑用 CLI 显式传参即可，不要以为改这个 YAML 会影响本地行为。

---

## 3. Prompt 构造（逐字完整）

来源：`swegemma/harness/agent_runner.py:55-190`（`build_agent_prompt`）与 `:497-739`（nudge 循环）。
每次调用还会把 prompt 记录进 trace：`trace.record_custom('task_prompt', initial_prompt, author='harness')`（`agent_runner.py:463-467`）。

### 3.1 初始 prompt 模板（逐字，按代码拼接顺序）

prompt 由 `prompt_parts` 用 `'\n'.join(...)` 拼成（`agent_runner.py:190`）。共 7 段，后 4 段条件性出现。

**段 1（永远有）** — `agent_runner.py:106-108`
```
You are evaluating a software engineering task for repository {task.repo}.

Problem Statement:
{task.problem_statement}
```
（f-string 字面量：`f'You are evaluating a software engineering task for repository {task.repo}.\n\nProblem Statement:\n{task.problem_statement}\n'`）

**段 2（仅当 `task.hints_text` strip 后非空）** — `agent_runner.py:109-111`
```
## Hints:
{hints.strip()}
```

**段 3（仅当 budget_lines 非空；默认配置下一定有）** — `agent_runner.py:113-118`
```
## Task Budget (Session terminates when any budget is exhausted)
{'\n'.join(budget_lines)}
```
`budget_lines` 的具体行由 `agent_runner.py:69-82` 生成，**逐字**：
```python
'- Time allowance: {config.budget.time_minutes} minutes'
'- Tool calls allowance: {config.budget.tool_calls} calls'
'- Max loop iterations: {config.budget.turns} turns'
'- Cost budget: ${config.budget.cost_usd:.2f} USD'
```
（仅当对应字段 `is not None` 才追加。默认 CLI 下**只有第一行**：`- Time allowance: 60.0 minutes`。）

**段 4（永远有）** — `agent_runner.py:84-104, 119-122`
```
## Execution Environment Rules
- Single command timeout: 300 seconds (commands exceeding this fail without ending the session)
- Command output limit: 5000 characters
- File view limit: 150 lines per read_file call
- File character limit: 10000 characters per read_file call
- Environment is offline (no network/PyPI access). All repository and test dependencies are ALREADY pre-installed. Do NOT attempt to run pip install or download packages.
```
生成代码（逐字）：
```python
harness_lines.append(
    f'- Single command timeout: {config.harness.command_timeout_seconds} seconds (commands exceeding this fail without ending the session)'
)
harness_lines.append(
    f'- Command output limit: {config.harness.max_stdout_chars} characters'
)
harness_lines.append(
    f'- File view limit: {config.harness.max_file_lines} lines per read_file call'
)
harness_lines.append(
    f'- File character limit: {config.harness.max_file_chars} characters per read_file call'
)
harness_lines.append(
    '- Environment is offline (no network/PyPI access). All repository and test dependencies are ALREADY pre-installed. Do NOT attempt to run pip install or download packages.'
)
```

**段 5（永远有）** — `agent_runner.py:124-142`，逐字：
```
## Instructions:
0. All source code is under `/workspace`. Do NOT search outside `/workspace` (e.g. `/usr/`, `/wheels/`, system site-packages). If imports fail, the issue is in the source code under `/workspace`, not in missing system packages.
1. Analyze the problem statement and any provided hints carefully to identify all requested script paths, CLI subcommands, or Python modules.
2. Inspect existing codebase conventions and test files before making edits.
3. <见下方分支>
4. Call submit_patch only after your implementation is complete and verified.
5. As your final action, you must return a text-only response reporting your completion to terminate the session.
```
第 3 条二选一（`agent_runner.py:130-137`）：

- `enable_sandbox_testing == False` 时：
```
3. The `pytest` and `unittest` test frameworks are intentionally disabled in this sandbox to avoid test sweeps and pre-existing environment failure loops. Do NOT import `unittest` or run test discovery. To verify your implementation, run targeted inline assertions via `python3 -c "..."` without unittest.
```
- 否则（**默认，`EvalConfig.enable_sandbox_testing = True`**，`config.py:122`）：
```
3. Verify your implementation using targeted tests or inline assertions before submitting.
```

**段 6（条件性：graph + embedding 均可用）** — `agent_runner.py:144-181`，逐字：
```
## Code Intelligence Tools
This repository has pre-built code graph and embedding data. Use these tools for fast, targeted navigation:
- `search_similar_code(query)`: Find semantically similar functions/classes by keyword.
- `get_code_neighbors(node)`: Find callers, callees, and definitions related to a symbol.
- `get_code_subgraph(nodes)`: Get the induced subgraph for a set of symbols.
```

**段 7（条件性：`workspace_tree` 非空）** — `agent_runner.py:183-188`，逐字：
```
## Workspace Layout
The repository is located at `/workspace`. Here is the directory tree (up to 3 levels):
```
+ 三反引号包裹的 tree + 换行 + 三反引号

树由 `agent_runner.py:311-317` 抓取：
```bash
cd /workspace && find . -maxdepth 3 -not -path "./.git/*" -not -name "*.pyc" -not -name "__pycache__" | sort | head -150
```

### 3.2 三类 nudge 文本（逐字，一字不差）

nudge 逻辑在 `agent_runner.py:689-739`。当一轮 `runner.run_async` 结束且 `context.patch_submitted` 仍为 False、且预算未耗尽时触发。

**判定顺序（`agent_runner.py:689-715`）：**

```python
is_length_truncation = False
if last_event_finish_reason is not None:
    fr_str = str(last_event_finish_reason).upper()
    if 'MAX_TOKENS' in fr_str or 'LENGTH' in fr_str:
        is_length_truncation = True

has_truncated_tool_call = '<|tool_call>' in last_assistant_text
```

**Nudge ① —— 工具调用被截断**（`has_truncated_tool_call`，`agent_runner.py:697-703`），逐字：
```
Your previous response reached the token limit before the tool call finished closing (<|tool_call|> was cut off). Do NOT repeat your prior reasoning in thought—emit your next tool call immediately, and if calling edit_file or write_file, split the change into smaller incremental edits.
```

**Nudge ② —— thinking 被截断（`finish_reason` 含 `MAX_TOKENS`/`LENGTH`）**（`agent_runner.py:704-710`），逐字：
```
Your previous response reached the token limit while thinking before a tool call was completed. Do NOT repeat your analysis in thought—keep reasoning under a few sentences and emit your next tool call immediately, or call submit_patch when you have completed and verified your changes.
```

**Nudge ③ —— 普通停轮未提交**（`agent_runner.py:711-715`），逐字：
```
Please continue your work using the available tools, or call submit_patch when you have completed and verified your changes.
```

nudge 以 `role='user'` 的 `Content` 注入（`agent_runner.py:736-739`），并记录：`trace.record_custom('continuation_nudge', nudge_prompt, author='harness')`（`:723-725`）。

**注意判据细节**：`'<|tool_call>' in last_assistant_text` 判断的是**不带斜杠的**开标签（只有开标签才会残留），但文本里写的是 `<|tool_call|>`。`last_assistant_text` 只累积 `event_author not in {'user','harness','system','tool'}` 且 `not part.thought` 的文本（`agent_runner.py:540-545`）。

### 3.3 循环终止条件全表（`agent_runner.py:498-739`）

| 条件 | 行号 | agent_error |
| :--- | :--- | :--- |
| 轮内：agent 已 `submit_patch` 且发出纯文本 final response | `:556-579` | — （break） |
| 轮内：`elapsed_seconds > timeout_sec` | `:581-589` | `Agent exceeded session timeout ({min} min)` |
| 轮内：`TimeoutError` / `LlmCallsLimitExceededError` | `:741-753` | 同上 / `Agent exceeded turns budget` |
| `remaining_turns <= 0` | `:504-514` | `Agent exceeded turns budget ({turns} turns)` |
| `context.patch_submitted` | `:635-637` | —（break） |
| `elapsed_seconds > timeout_sec` | `:639-645` | timeout |
| `tool_calls_used >= budget.tool_calls` | `:647-660` | `Agent exceeded tool call budget ({n} calls)` |
| `llm_calls_used >= max_llm_calls` | `:662-672` | turns |
| `consecutive_nudges >= 3` | `:680-686` | **不设 agent_error**（只是 break） |
| 正常结束但无 patch 且工作区无改动 | `:760-795` | `Agent completed execution without calling submit_patch.` |

**Patch 兜底提取（`agent_runner.py:758-795`）**：若从未调用 `submit_patch`，harness 会自己跑
```bash
cd /workspace && git add -N .
cd /workspace && (git diff --binary _swegemma_baseline 2>/dev/null || git diff --binary HEAD)
```
若有非空 diff，就把它当 `agent_patch`（**且保留 agent_error**）→ `evaluate.py:324` 的条件 `agent_error and not agent_patch` 不成立 → **仍然进 Phase 2**。

> ⚠️ README `:557-558` 写的是 `git diff HEAD`，实际代码用的是 `git diff --binary _swegemma_baseline || git diff --binary HEAD`（`--binary` + baseline tag 优先）。

---

## 4. Code Intelligence 工具的真实行为

### 4.1 启用条件

**工具注册是永远发生的，不依赖任何条件**（`tools/__init__.py:34-46`）：
```python
def create_tools(ctx: Any) -> dict[str, Callable]:
    return {
        'run_command': make_run_command(ctx),
        'read_file': make_read_file(ctx),
        'write_file': make_write_file(ctx),
        'edit_file': make_edit_file(ctx),
        'submit_patch': make_submit_patch(ctx),
        'get_status': make_get_status(ctx),
        'get_code_neighbors': make_get_code_neighbors(ctx),
        'search_similar_code': make_search_similar_code(ctx),
        'get_code_subgraph': make_get_code_subgraph(ctx),
    }
```
**9 个工具全部无条件注册**。能不能被 agent 用，取决于提交的 `agent.yaml` 里 `tools:` 列了哪些名字（`adk_submission` 的 `ToolRegistry` 解析）。

**被「启用」的只是 prompt 里那一段广告文案**（`agent_runner.py:144-181`）：

```python
graph_available = False
if getattr(config, 'graph_dir', None) and getattr(config, 'embeddings_dir', None):
    repo_str = getattr(task, 'repo', '') or ''
    repo_short = repo_str.split('/')[-1] if repo_str else ''
    repo_slug = repo_str.replace('/', '_') if repo_str else ''
    base_commit = getattr(task, 'base_commit', None)
    g_candidates = []; e_candidates = []
    if base_commit:
        g_candidates.extend([Path(graph_dir)/f'{repo_short}_{base_commit}.json',
                             Path(graph_dir)/f'{repo_slug}_{base_commit}.json'])
        e_candidates.extend([Path(embeddings_dir)/f'{repo_short}_{base_commit}.npz',
                             Path(embeddings_dir)/f'{repo_slug}_{base_commit}.npz'])
    g_candidates.extend([Path(graph_dir)/f'{repo_slug}.json', Path(graph_dir)/f'{repo_short}.json'])
    e_candidates.extend([Path(embeddings_dir)/f'{repo_slug}.npz', Path(embeddings_dir)/f'{repo_short}.npz'])
    has_g = any(p.exists() and p.stat().st_size > 100 for p in g_candidates)
    has_e = any(p.exists() and p.stat().st_size > 100 for p in e_candidates)
    if has_g and has_e:
        graph_available = True
```

**启用判定 = 路径存在 且 `st_size > 100` 字节，且 graph 与 embedding 两侧都要满足。**
候选路径按 `{repo_short}_{base_commit}` → `{repo_slug}_{base_commit}` → `{repo_slug}` → `{repo_short}` 顺序；`repo_short` = `repo.split('/')[-1]`，`repo_slug` = `repo.replace('/','_')`（对 `fastapi/fastapi` 二者都是 `fastapi`）。

目录默认值：`EvalConfig.graph_dir = 'data/graphs'`、`embeddings_dir = 'data/embeddings'`（`config.py:100-101`），`__post_init__` 会在 `data/graphs` 不存在时**自动回退**到 `tasks_path.parent/'graphs'`、`tasks_path.parent/'embeddings'`（`config.py:195-207`）。

本地实测：`data/embeddings/` 只有 6 个 `.npz`，其中 **4 个是 0 字节**；`data/graphs/` **整个目录不存在**。→ 本地 `graph_available` 恒为 `False`，prompt **不会**出现 Code Intelligence 段。而 Kaggle 侧已知「129/256 个 graph/embedding 文件为 0 字节」——按 `st_size > 100` 判据，**这 129 个 0 字节文件对应的任务一律不显示广告段**。

### 4.2 `search_similar_code` 在离线沙箱里实际怎么算相似度

**结论：完全没有 embedding 模型。没有 sentence-transformers / ONNX / transformers / torch。** 只有「节点名查表 + 预存向量的余弦相似度」。README `:492` 也承认这一点。

调用链（`tools/graph.py:84-153` → `graph/retrieval_utils.py:236-413`）：

1. `repo_name` 从 `ctx.repo` / `task.repo` 取；为空返回 `MissingRepoContext`（`tools/graph.py:108-117`）
2. `base_commit` 若已被 `repo_name` 以 `_{base_commit}` 结尾包含，则置 `None`（`tools/graph.py:122-126`）
3. `sg.get_similar_nodes(node=query, repo_name=..., k=k, graph_dir=..., embeddings_dir=..., base_commit=...)`
4. `get_similar_nodes` 内部：
   - `query` 是 `str` 且不含 `;` → `node_name = query`（`retrieval_utils.py:270-279`）
   - 查 `_SIMILARITY_CACHE` → 查 `_PRECOMPUTED_GRAPHS`（**评测路径上永远是空的**，因为 `precompute_top_k_similar_nodes` 没有任何调用点）
   - `graph = graph_utils.get_graph(...)` —— **图 JSON 不存在会抛 `KeyError`**，被 `tools/graph.py:149-153` 包成 `SimilaritySearchError`
   - `resolve_node_name(query, graph)` 把 query 收敛到具体节点
   - `_extract_nodes_and_embeddings(graph, ...)`（`retrieval_utils.py:56-137`）：
     - 每个节点的向量优先取 `attrs['embedding']`（图 JSON 里通常被 `include_embeddings=False` 剥掉了，见 `graph_utils.py:55-67`）
     - 取不到则 `embedding_utils.embed(node_name, repo, embeddings_dir, base_commit)` 从 **`.npz` 里按节点名字典查**
     - **仍然取不到 → 填 `np.zeros((dim,))`**，`dim` = 第一个成功向量长度，否则 `DEFAULT_EMBEDDING_DIM = 128`（`embedding_utils.py:16`）
   - `query_emb = embedding_utils.embed(node_name, ...)`（`retrieval_utils.py:363-369`）
   - **`if query_emb is None: return []`（`retrieval_utils.py:371-372`）** ← **这就是「query 不是节点名 → 空结果」的根因**
   - 否则：`dots = np.dot(emb_matrix, query_emb); sims = dots / (matrix_norms * q_norm)`，`np.argsort(sims)[::-1]` 取 top-k，跳过自身（`retrieval_utils.py:374-407`）

`embedding_utils.embed()` 的查表层级（`embedding_utils.py:196-209`）：
```python
if node_str in repo_cache: return repo_cache[node_str]
if repo_str and not node_str.startswith(f'{repo_str};'):
    alt_key = f'{repo_str};{node_str}'
    if alt_key in repo_cache: return repo_cache[alt_key]
for k in repo_cache:
    if k == node_str or k.endswith(f'.{node_str}') or k.endswith(f';{node_str}'):
        return repo_cache[k]
return None
```

**关键坑（严重）**：所谓「语义相似检索」实际是
> 用 query **字符串**去 `.npz` 的 key 集合里做「精确 / `owner/repo;name` / `.name` / `;name` 后缀」匹配，取到预存向量后与其它节点预存向量算余弦。

所以：
- `search_similar_code("parse the config file")` → **返回 `{"status":"ok","results":[],"count":0}`**（`embed` 返回 None → `get_similar_nodes` 返回 `[]`），**不报错**，agent 容易误以为「没相似代码」。
- `search_similar_code("HTTPConnection")` 只有在 `.npz` 里恰好有 `HTTPConnection` 或以 `.HTTPConnection` / `;HTTPConnection` 结尾的 key 时才有结果。
- 本地 `.npz` 文件缺失/0 字节时，每个节点向量都被填成 **全 0**；`matrix_norms` 被抬到 `1e-10`，`dots` 也全 0 → `sims` 全 0，排序退化为**节点插入顺序**（`argsort` 稳定版对全等值保留原序），返回的 top-k 是「图里最前面的 k 个节点」。这是**最危险的静默失败模式**：看起来有结果，实际全是噪声。

### 4.3 `resolve_node_name` 的匹配层级

`graph_utils.py:149-204`，**4 层**（docstring 里写 1..4，但代码里「精确」是提前 return 的第 0 层）：

| 层 | 规则 | 代码 | 多候选时的选择 |
| :-- | :--- | :--- | :--- |
| 0 | `query in graph`（节点名精确相等） | `:170-171` | 直接返回 query |
| 1 | 后缀边界匹配：`str(n).endswith(f'.{query}')` 或 `endswith(f';{query}')` | `:173-181` | `min(candidates, key=lambda x: (len(str(x).split('.')), len(str(x))))` —— **层级最浅 + 名字最短**（类优先于方法） |
| 2 | 大小写不敏感：`str(n).lower() == lower_query` 或 `.lower().endswith(f'.{lower_query}')` / `;{lower_query}` | `:183-193` | 同上 |
| 3 | 子串包含：`query in str(n)` 或 `lower_query in str(n).lower()` | `:195-202` | 同上 |
| — | 全部落空 → `return None` | `:204` | 调用方 `get_neighbor` 返回 `[]`（`graph_utils.py:331-334`） |

> README `:482` 写「exact → `.` 或 `/` 后缀 → 大小写不敏感 → 子串」，其中「`/` 后缀」是**错的**，实际后缀分隔符是 `.` 和 `;`。

### 4.4 图里实际有哪些边类型

代码侧**不硬编码任何边类型**。`get_code_subgraph` 只读属性 `data.get('type') or data.get('relation') or 'connected'`（`tools/graph.py:207-214`）；`get_neighbor` 的 `edge_type` 过滤同时兼容 `data['type']` 与 `data['relation']`（`graph_utils.py:340-356`）。也就是说边类型完全由**预构建的 graph JSON** 决定。

README 举的例子是 `CALLS` / `DEFINED_IN` / `IMPORTS`（README `:483`、`tools/graph.py:26,239` docstring），但这是**文档示例，不是枚举约束**。本地**没有任何 graph JSON 文件**（`data/graphs/` 不存在，全树找不到 `*_graph*.json`），所以**无法从本地代码或数据核实真实边类型集合**——这是本次分析的可见边界，需要在 Kaggle 侧数据上采样确认。

### 4.5 0 字节 / 缺失文件的代码分支（核实结论）

| 文件状态 | 触发点 | 代码分支 | 结果 |
| :--- | :--- | :--- | :--- |
| graph JSON **缺失** | `get_graph` 候选全部 `os.path.exists` 为假 | `graph_utils.py:252-253` `raise KeyError(f'Repository {repo_name} topology not found at: {local_path}')` | 工具层捕获 → `{"status":"error","error_type":"GraphLookupError"/"SubgraphExtractionError"/"SimilaritySearchError"}`（`tools/graph.py:77-81,149-153,222-226`） |
| graph JSON **0 字节** | `os.path.exists` 为 **True** → 被选为 `local_path` | `load_graph_from_json` → `json.load(f)` 抛 `json.JSONDecodeError`（`graph_utils.py:133-134`） | **同上，抛异常**。注意：0 字节文件会**遮蔽**候选列表里后面的有效文件（`next((p for p in candidates if os.path.exists(p)), ...)`，`:250` 只看存在性） |
| embedding NPZ **缺失** | `embed()` 里 `os.path.exists(file_path)` 为假 | `embedding_utils.py:187-194` 跳过加载，`_REPO_CACHES[cache_key] = {}` | 查表落空 → `embed()` 返回 `None` |
| embedding NPZ **0 字节** | `os.path.exists` 为 True → `load_embeddings_from_npz` | `np.load(zero_byte_file, allow_pickle=False)` 抛 `BadZipFile`/`ValueError` → 被 `try/except Exception` 吞掉，记 `logger.warning('Failed to load embeddings from %s: %s', ...)`（`embedding_utils.py:188-193`） | **cache = {}**，行为与「缺失」等价，只是多一条 warning |
| NPZ 有效但 **query 不在 key 中** | `embed()` 三层查表全落空 | `embedding_utils.py:211` `return None` | `search_similar_code` 返回 **空 results**（不是错误） |
| NPZ 有效但**部分节点**无向量 | `_extract_nodes_and_embeddings` | `retrieval_utils.py:116-130` 填 `np.zeros(target_dim)` | **静默降级为噪声排序** |

**prompt 广告门槛（`>100` 字节）与实际加载逻辑（`os.path.exists`）不一致**：
- 只要文件 `>100` 字节就登广告 → 一个 101 字节的坏 JSON 也会让 prompt 宣称「有预构建图数据」，然后每次调用都报错。
- 反过来，0 字节文件不会登广告，但**工具仍然可调**（`create_tools` 无条件注册），agent 若凭 `agent.yaml` 主动调用，会拿到上述错误/空结果。

---

## 5. `edit_file` 的 3 层匹配算法

真实实现在 `adk_eval_core/editing/edit.py`；`swegemma/edit.py` 只是薄封装（加 diff + 把 `EditResult` 转成 `AppliedEdit` 并把 `error_message` 转成 `ValueError`）。

### 5.0 工具侧前置动作（`swegemma/tools/workspace.py:179-251`）

1. `_resolve_workspace_path(filepath, allow_root=False)` —— 越界（绝对路径 / `..`）抛 `Path traversal detected`（`workspace.py:17-50`）
2. `ctx.docker.copy_from(ctx.container_id, dest_path, local_file)` 把文件从沙箱拉到宿主临时目录
3. **`with open(local_file, encoding='utf-8', errors='replace', newline='') as f`** —— `newline=''` 意味着**保留原始 `\r\n`，代码里没有 CRLF→LF 归一化**（README `:449` 声称「after normalizing `\r\n` → `\n`」，**与代码不符**）
4. **`if len(content) == 0: raise ValueError(f"File '{filepath}' is empty. Use write_file to populate...")`**（`workspace.py:215-218`）
5. `apply_replacement(...)` → 写回 → `docker.copy_to` 回沙箱
6. 返回 diff（截断到 `max_stdout_chars = 5000`）

### 5.1 派发顺序（`edit.py:308-354`）

```python
def apply_replacement(current_content, old_string, new_string, allow_multiple=False) -> EditResult:
    if not old_string:
        return EditResult(..., strategy="none", error_message="old_string cannot be empty for existing files.")
    if old_string == new_string:
        return EditResult(..., strategy="exact",
                          error_message="No changes to apply. old_string and new_string are identical.")
    # 1. Exact
    exact_res = _apply_exact_match(...)
    if exact_res: return exact_res
    # 2. Flexible
    flex_res = _apply_flexible_match(...)
    if flex_res: return flex_res
    # 3. Regex
    regex_res = _apply_regex_match(...)
    if regex_res: return regex_res
    return EditResult(..., strategy="none",
        error_message=("Failed to replace: old_string not found. "
                       "Ensure you're not escaping content incorrectly and check whitespace, indentation, and context."))
```
**任一层的返回值（含 `error_message` 的失败结果）都会立刻 `return`，不会继续降级。** 这是最重要的一条：**第 1 层「多重匹配」失败会直接终止，不会尝试第 2/3 层。**

### 5.2 第 1 层：exact（`edit.py:109-135`）

```python
exact_count = current_content.count(old_string)
if exact_count == 0: return None          # → 降级到 flexible
if not allow_multiple and exact_count > 1:
    return EditResult(new_content=current_content, occurrences=exact_count, strategy="exact",
        error_message=f"Expected 1 occurrence but found {exact_count}. "
                      "If you intended to replace multiple occurrences, set 'allow_multiple' to true.")
new_content = current_content.replace(old_string, new_string)
```
- 规则：**逐字符子串匹配**（`str.count`），无任何归一化、无空白容忍
- `old_string` 出现 1 次 → 替换成功，`strategy="exact"`
- 出现 0 次 → 返回 `None`，降级
- 出现 ≥2 次且 `allow_multiple=False` → **报错终止**
- `allow_multiple=True` → 全部替换

### 5.3 第 2 层：flexible（`edit.py:138-236`）

把内容按 `splitlines(keepends=True)` 切行，`old_string` / `new_string` 用 `splitlines()` 切。

**Pass 1（rstrip 匹配）**：滑动窗口逐行 `line.rstrip()` 比较。
```python
norm_old_rstrip = [line.rstrip() for line in old_lines]
i = 0
while i <= len(current_lines) - len(old_lines):
    window = current_lines[i : i + len(old_lines)]
    if [line.rstrip() for line in window] == norm_old_rstrip:
        matches.append(i); i += len(old_lines)     # 命中后跳整块
    else:
        i += 1
```
（`rstrip()` 会吃掉 `\r`，所以 **CRLF 差异在这一层被消化**。）

**Pass 2（strip 匹配，仅当 Pass 1 零命中）**：`line.strip()` 比较，**连缩进一起忽略**。

**多候选**：`if not allow_multiple and len(matches) > 1` → 报错终止（`strategy="flexible"`）。

**重新缩进**（关键副作用）：
```python
old_ref_indent = min((len(l) - len(l.lstrip()) for l in old_lines if l.strip()), default=0)
new_ref_indent = min((len(l) - len(l.lstrip()) for l in new_lines if l.strip()), default=0)
relative_indent_delta = max(0, new_ref_indent - old_ref_indent)
...
non_empty_window = [l for l in window if l.strip()]
min_line = min(non_empty_window, key=lambda l: len(l) - len(l.lstrip()))
indent = re.match(r"^([ \t]*)", min_line).group(1)      # 匹配位置的实际缩进
target_indent = indent + (" " * relative_indent_delta)
indented_new = apply_indentation(new_lines, target_indent)
```
`apply_indentation`（`edit.py:93-106`）：以 `new_lines` 中非空行的**最小缩进**为基准 `ref_indent`，输出 `target_indent + line[ref_indent:]`。

**行尾处理**：按匹配窗口最后一行的结尾（`\r\n` / `\n` / 无）补齐或剥掉换行（`edit.py:217-226`）。替换**自底向上**执行（`for match_idx in reversed(matches)`），避免索引失效。

### 5.4 第 3 层：regex（`edit.py:239-305`）

**Token 化 `old_string`**：
```python
token_pattern = re.compile(
    r"==|!=|<=|>=|->|:=|\+=|-=|\*\*|//|[():\[\]{},><=+\-*/]|\w+|\S+"
)
tokens = token_pattern.findall(old_string)
```
**拼接正则**：相邻两个 token 都是 `\w+` → 用 `\s+` 连接；否则用 `\s*`（`edit.py:252-262`）。每个 token 用 `re.escape`。

**最终模式**（`edit.py:263`）：
```python
final_pattern = f"^([ \t]*){pattern_str}[ \t]*(?=\\r?\\n|$)"
matches = list(re.finditer(final_pattern, current_content, flags=re.MULTILINE))
```
- 强制**行首锚定**（前导 `[ \t]*` 被捕获为缩进组）
- 强制**行尾收束**（lookahead `\r?\n|$`）
- `\s*` / `\s+` **可以匹配换行**，所以 token 序列能跨行匹配

**多候选**：`len(matches) > 1 且 not allow_multiple` → 报错终止。替换时 `re.sub(..., count=0 if allow_multiple else 1)`，缩进用 `match.group(1)` 重新应用。

**风险**：因为是 token 级 + 空白全模糊，**它可能在完全没料到的地方匹配上**。判据只看「匹配次数」，不看语义。这是三层里最危险的一层。

### 5.5 什么情况会失败

| 失败 | 层 | 报错文本（`FileEditError.error_message`） |
| :--- | :--- | :--- |
| `old_string` 为空 | 前置 | `old_string cannot be empty.`（`swegemma/edit.py:50-51`，先于 core） |
| `old_string == new_string` | 前置 | `No changes to apply. old_string and new_string are identical.` |
| 文件不存在 | 工具 | `File '...' not found in workspace.` |
| **文件 0 字节** | 工具 | `File '...' is empty. Use write_file to populate an empty or newly created file.` |
| 路径越界 | 工具 | `Path traversal detected: '...' escapes workspace root.` |
| exact 命中 ≥2 次（`allow_multiple=False`） | 1 | `Target string occurs N times in <file>. Please provide more surrounding context.`（`swegemma/edit.py:63-66`） |
| flexible 命中 ≥2 次 | 2 | `Target string flexibly matches N locations in <file>. Please provide more surrounding context.`（`swegemma/edit.py:58-62`） |
| regex 命中 ≥2 次 | 3 | `Target string occurs N times in <file>. Please provide more surrounding context.`（`swegemma/edit.py:63-66`，注意这里**没有** flexible 分支的专门文案） |
| 三层全 0 命中 | 3→终 | `Failed to replace: old_string not found. Ensure you're not escaping content incorrectly and check whitespace, indentation, and context.` |

### 5.6 怎样让 agent 的 edit 成功率最高

按代码行为推出的可执行清单：

1. **`old_string` 必须唯一**。第 1 层只要命中 ≥2 次就直接报错、**不降级**。给 **2–4 行上下文**（docstring `workspace.py:189-190` 也这么建议），把匹配块扩展到包含函数签名或唯一的相邻语句。
2. **`old_string` 的基准缩进要与文件里完全一致**（第 1 层是逐字符）。若不确定，**故意把缩进写错反而更安全**：让第 1 层 miss，落到第 2 层 strip 匹配，由 harness 自己重排缩进。
3. **`new_string` 的相对缩进要和 `old_string` 一致**。flexible 层的 `apply_indentation` 会把 `new_string` 整体平移到「匹配位置的缩进 + `max(0, new_min_indent - old_min_indent)`」。如果 `new_string` 首行带了多余绝对缩进，`relative_indent_delta > 0`，**整块会被多推空格**，Python 缩进直接坏掉。**推荐 `new_string` 从第 0 列开始写，块内相对缩进与 `old_string` 保持同构。**
4. **不要跨文件复用同一段代码片段**（`pass`、`return None`、`import os` 这类）。

   | ❌ 坏 | ✅ 好 |
   | :--- | :--- |
   | `old_string="    return None\n"` | `old_string="def parse(self, raw):\n    if not raw:\n        return None\n"` |
5. **优先 `edit_file` 而不是 `write_file`**：`write_file` 要整文件重打，token 消耗大，且容易在 `max_output_tokens` 处被截断（触发 Nudge ①）。
6. **大改动拆成多次小 `edit_file`**。Nudge ① 的文案就是官方建议：`split the change into smaller incremental edits`。建议配合 `generate_content_config: {max_output_tokens: 16384, thinking_config: {thinking_budget: 4096}}`（`config.py:59-67` 的默认约束）。
7. **先 `read_file` 拿原文再 edit**。`read_file` 默认只给 150 行 / 10000 字符且会截断（`workspace.py:114-126`），所以对大文件要用 `start_line` / `end_line` 分段读，确保 `old_string` 的字面量与磁盘一致（包括行尾）。
8. **CRLF 文件不必特殊处理**：第 1 层会 miss，第 2 层的 `rstrip()` 会救回来（`rstrip` 同时吃掉 `\r` 和空格）。
9. **`allow_multiple=True` 只在明确要全量替换时用**（例如统一改签名），否则会误伤。
10. **不要试图改测试文件**：`verify_task` 的 `git checkout HEAD --` + `git clean -f --` 会把受保护路径上的改动全部丢弃（`verification.py:389-415`）。改测试 = 白干 + 可能因为改了 `conftest.py` 让本地自测结果与最终判定不一致。
11. **在 `/workspace` 里不要留 scratch 脚本**：`submit_patch` 用 `git add -N .`，会把 `repro.py` 之类的未跟踪文件一起打进 patch（README `:649`）。临时脚本放 `/tmp`。
12. **调完立刻调 `submit_patch()`**（不消耗工具预算，`tools/execution.py:40`），它是唯一能让 harness 干净退出的方式。

---

## 6. submission 校验（硬性拒绝条件）

校验实现在 `adk_submission`（`validate_directory` + Pydantic schema + 各 resolver），**触发点是 `compile_submission`**，即 `swegemma/harness/agent_runner.py:334-346` —— **每个 task 每次 run 都会重新编译 + 重新校验一次，没有独立的 pre-flight 阶段**。

### 6.1 调用链

```
swegemma/cli.py:140          models = setup_gemma_model_registry(models_yaml_path=args.models_yaml)
swegemma/cli.py:141-159      config = EvalConfig(..., submission_dir=args.submission_dir, models=models, ...)
                             └─ EvalConfig.__post_init__           config.py:142-146
                                  limits, gen = build_submission_limits()   ← 收窄版 limits 注入
swegemma/cli.py:161-162      asyncio.run(Evaluator(config).run())
swegemma/evaluate.py:393     Evaluator.run
swegemma/evaluate.py:221     evaluate_task
swegemma/evaluate.py:194-207 _run_agent_sandbox
swegemma/harness/agent_runner.py:193   run_agent_sandbox
swegemma/harness/agent_runner.py:334   agent = compile_submission(
                                 submission_dir=config.submission_dir,
                                 tool_registry=tools,
                                 model_registry=config.models,
                                 limits=config.limits,                     ← swegemma 收窄版
                                 generation_constraints=config.generation_constraints,
                                 adapter_manifest=config.adapter_manifest, ← 默认 None
                                 ...)
```

`adk_submission` 内部（`compiler.py:59 compile_submission`）：
```
:116-120  ToolRegistry 强制转换
:122      limits = limits or SubmissionLimits()
:125      validate_directory(submission_dir, limits)      → discovery.py:60
            ├─ :96   set_active_limits_for_root(...)
            ├─ :99-105  递归扫描：任何符号链接 → 拒
            ├─ :110-119 文件数 / 总大小
            ├─ :121-127 扩展名白名单
            ├─ :129-139 分类 yaml / prompt / adapter
            ├─ :141-165 YAML 数 / 单 YAML 大小 / skill 目录大小
            └─ :168  find_root_config(root, yaml_files)  → discovery.py:180
:128-131  discover_adapters(root_dir, limits.adapter_extensions)
:134      load_yaml(config_path, root_dir, limits=limits)
:137-140  SandboxedAgentConfig.model_validate(raw_config) → SubmissionSchemaError
:143-186  AgentClassFactory 注入
:189-203  _compile_agent(config.root, ctx)  → :225 agent_count 检查
            ├─ builders/llm.py:33         compile_llm_agent
            │    ├─ context.py:127,156    instruction / description 长度
            │    ├─ resolvers/tools.py:38 resolve_tool_item  → ToolNotFoundError
            │    ├─ resolvers/tools.py:129 resolve_skills    → SkillNotFoundError / max_skills
            │    ├─ resolvers/models.py:27 resolve_model     → ModelNotFoundError / AdapterNotFoundError
            │    ├─ resolvers/callbacks.py:27 resolve_callbacks → CallbackNotFoundError
            │    ├─ builders/sub_agents.py:17 compile_sub_agents → depth 检查 + 递归
            │    └─ resolvers/generation.py:19 resolve_generation_config → limits.py:309
            ├─ builders/workflows.py:40,71   Sequential/Parallel
            └─ builders/workflows.py:102     LoopAgent → max_loop_iterations 检查
:204-205  finally: clear_active_limits_for_root(root_dir)
```

> **注意**：`validate_single_declared_model`（`swegemma/models/discovery.py:93`）在整个 vendored 源码里**只有定义与导出、没有调用点**（实测 grep 仅命中 `models/discovery.py:93` 与 `models/__init__.py:7,32`）。同理 `generate_standard_submission`（`swegemma/submission.py:35`）。二者属于**未随包分发的 Kaggle metric notebook**，因此「单模型规则」在执行时序上**早于** `compile_submission`。

### 6.2 `SubmissionLimits`：赛事收窄版 vs 库默认版

**赛事实际生效值**（`swegemma/config.py:19-31` + `:34-68` 的 `build_submission_limits()`）：

```python
MAX_SUBMISSION_SIZE_BYTES: int = 3 * 1024 * 1024 * 1024  # 3 GiB (3,221,225,472 bytes)
ALLOWED_SUBMISSION_EXTENSIONS: frozenset[str] = frozenset(
    {'.yaml', '.yml', '.md', '.txt', '.py', '.json', '.safetensors'}
)
ALLOWED_ADAPTER_EXTENSIONS: frozenset[str] = frozenset({'.safetensors'})
```

| 字段 | **赛事实际值** | 库默认值（`limits.py:184-195`） | 出处 |
| :--- | :--- | :--- | :--- |
| `max_total_size_bytes` | **3,221,225,472 (3 GiB)**，解压后含 `adapters/` | 同 | `config.py:19,45`；`limits.py:184` |
| `allowed_file_extensions` | **仅 7 种** | **30 种**（`limits.py:103-135`，含 `""`、`.bin`、`.pt`、`.sh`、`.ps1`…） | `config.py:20-30,56` |
| `adapter_extensions` | **仅 `.safetensors`** | 6 种（`.safetensors,.bin,.pt,.pth,.gguf,.ggml`，`limits.py:137-146`） | `config.py:31,57` |
| `max_file_count` | 10,000 | 同 | `config.py:48`；`discovery.py:111` |
| `max_yaml_files` | 1,000 | 同 | `config.py:49`；`discovery.py:141` |
| `max_instruction_chars` | 1,000,000（单 agent；`description` 同限） | 同 | `config.py:50`；`context.py:143,175` |
| `max_total_instruction_chars` | 10,000,000（含 skill 文本） | 同 | `config.py:51`；`context.py:149` |
| `max_agents` | 500 | 同 | `config.py:52`；`compiler.py:226` |
| `max_sub_agent_depth` | 50 | 同 | `config.py:53`；`sub_agents.py:44` |
| `max_skills` | 1,000 | 同 | `config.py:54`；`tools.py:154` |
| `max_loop_iterations` | 500（`max_iterations` 不给则取此值） | 同 | `config.py:35,55`；`workflows.py:124-131` |
| `max_yaml_size_bytes` | 50 MiB（单文件 **且** `!include` 累计） | 同 | `config.py:46`；`limits.py:185` |
| `max_skill_size_bytes` | 50 MiB | 同 | `config.py:47`；`limits.py:186` |

**⚠️ 赛事收窄的直接后果（最容易踩的坑）**：下列文件在库默认下合法，**在本赛事一律被拒**：
`.bin` / `.pt` / `.pth` / `.gguf` / `.ggml`（PEFT 权重**必须是 safetensors**）、`.sh` / `.sql` / `.csv` / `.tsv` / `.patch` / `.diff` / `.html` / `.xml` / `.toml` / `.cfg` / `.ini` / `.rst` / `.jinja` / `.jsonl` / `.model` / `.tiktoken`，以及**所有无扩展名文件**（`Makefile`、`LICENSE`、`Dockerfile`、`.gitignore`、`requirements`）。

`SubmissionLimits.__post_init__`（`limits.py:198-220`）：前 9 个字段必须为正整数，`max_sub_agent_depth` / `max_skills` 必须 ≥ 0，否则 `ValueError`。

### 6.3 全部硬性拒绝条件（逐条）

#### （1）根配置唯一性 —— 最常踩的一条

`discovery.py:24`：
```python
_ROOT_CONFIG_NAMES: list[str] = ["agent.yaml", "root_agent.yaml"]
```

`discovery.py:199-251`（逐字）：
```python
    for name in _ROOT_CONFIG_NAMES:
        candidate = root / name
        if candidate.is_symlink():
            raise PathTraversalError(
                f"Root config path escapes submission directory via symlink: {candidate}"
            )
        if candidate.exists() and candidate.is_file():
            return validate_sandboxed_path(
                path=candidate, base_dir=root, must_exist=True,
                allow_symlinks=False,
                allowed_extensions={".yaml", ".yml"},
                error_prefix="Root config",
            )
    ...
    root_level_yamls = [p for p in yaml_files if p.parent == root]
    if len(root_level_yamls) == 1:
        return validate_sandboxed_path(...)
    if len(root_level_yamls) == 0:
        raise SubmissionValidationError(
            "No root YAML config found. Expected 'agent.yaml' or "
            "'root_agent.yaml' at the top level of the submission directory."
        )
    names = [p.name for p in root_level_yamls]
    raise SubmissionValidationError(
        f"Ambiguous root config: found {len(root_level_yamls)} YAML files "
        f"at the root level ({', '.join(names)}). Please name the root "
        f"config 'agent.yaml' or 'root_agent.yaml'."
    )
```

**精确规则：**

| 场景 | 结果 |
| :--- | :--- |
| 顶层有 `agent.yaml` | ✅ 胜出（**即使同时存在 `root_agent.yaml` 也不报错**） |
| 顶层只有 `root_agent.yaml` | ✅ 胜出 |
| 顶层无规范名，但恰好 1 个 `.yaml`/`.yml` | ✅ 用那一个 |
| 顶层**只有** `agent.yml`（或 `root_agent.yml`） | ⚠️ `agent.yml` / `root_agent.yml` **不在 `_ROOT_CONFIG_NAMES` 里**，靠「顶层唯一 YAML」规则兜住 |
| 顶层 0 个 YAML | ❌ `No root YAML config found` |
| 顶层 ≥2 个 YAML **且无规范名** | ❌ `Ambiguous root config: found N YAML files ...` |
| 规范名文件是符号链接 | ❌ `PathTraversalError` |
| 根配置在子目录（如 `src/agent.yaml`） | ❌ 不算根 → 顶层 0 个 YAML → 报错 |
| 多个 `agent.yaml` 分散在不同子目录 | ✅ 不冲突（只扫顶层） |

> 实测：`data/sample_submission/` 顶层只有 `agent.yaml` + `eval_config.yaml`（2 个 YAML）→ 走**规则 1**，`agent.yaml` 直接胜出，**不报 Ambiguous**。

#### （2）文件扩展名白名单

`discovery.py:121-127`（逐字，**先于根配置发现执行**）：
```python
    # --- Extension check ---
    for p in all_files:
        if p.suffix.lower() not in limits.allowed_file_extensions:
            raise SubmissionValidationError(
                f"File has disallowed extension '{p.suffix}': "
                f"{p.relative_to(root)}"
            )
```
对**全目录所有普通文件**生效（含 `adapters/`），大小写不敏感（`.YAML` 也过），只查普通文件不查目录。

#### （3）单模型规则

**不在 `adk_submission`，在 `swegemma/models/discovery.py:93-121`**（逐字）：
```python
def validate_single_declared_model(agent_dir: str | Path) -> str:
    models = discover_declared_models(agent_dir)

    if not models:
        raise ParticipantVisibleError(
            "No model declared in agent configuration. "
            "Expected exactly one model to be declared (e.g. 'gemma-4-31b-it')."
        )

    if len(models) > 1:
        sorted_models = sorted(models)
        raise ParticipantVisibleError(
            f"Ambiguous model declaration: multiple distinct models declared across "
            f"agent configuration ({sorted_models}). "
            "This competition requires all agents in a submission to share exactly one model."
        )

    return next(iter(models))
```
- **归一化**（`models/discovery.py:44-50`）：`strip().lower()` + 剥掉 `openai/`、`google/`、`hosted_vllm/`、`custom/` 前缀 → `openai/gemma-4-9b-it` 与 `gemma-4-9b-it` 视为**同一**模型，不冲突。
- **声明来源**（`adk_submission/discovery.py:592-747` `discover_declared_models`）：根配置 + `sub_agents[*].config_path` + `tools[*].agent_tool.config_path`，**再额外扫描目录内所有未被引用的 YAML**，只取含 `agent_class`/`instruction`/`tools`/`sub_agents` 任一键的「agent 型」YAML。→ **藏在一边没被引用的 YAML 里写了第二个模型也会被抓到。**
- ⚠️ 但此函数**在 vendored swegemma 内无调用者**，只在 Kaggle metric 侧执行。本地 `swegemma eval` 不会因多模型被拒（只会在 `resolvers/models.py` 解析别名时抛 `ModelNotFoundError`）。

#### （4）大小 / 数量 / 目录合法性

`discovery.py:91-94`：
```python
    if not root.is_dir():
        raise SubmissionValidationError(
            f"Submission path is not a directory: {submission_dir}"
        )
```

`discovery.py:110-119`、`:141-165`（逐字）：
```python
    if len(all_files) > limits.max_file_count:
        raise LimitExceededError(f"Too many files: {len(all_files)} (max {limits.max_file_count})")
    if total_size > limits.max_total_size_bytes:
        raise LimitExceededError(
            f"Total submission size {total_size:,} bytes exceeds "
            f"limit of {limits.max_total_size_bytes:,} bytes"
        )
```
```python
    if len(yaml_files) > limits.max_yaml_files:
        raise LimitExceededError(f"Too many YAML files: {len(yaml_files)} (max {limits.max_yaml_files})")

    for yf in yaml_files:
        yf_size = yf.stat().st_size
        if yf_size > limits.max_yaml_size_bytes:
            raise LimitExceededError(f"YAML file '{yf.relative_to(root)}' size {yf_size:,} bytes exceeds limit of {limits.max_yaml_size_bytes:,} bytes")

    for sf in all_files:
        if sf.name == "SKILL.md":
            skill_dir = sf.parent
            skill_size = sum(f.stat().st_size for f in skill_dir.rglob("*") if f.is_file())
            if skill_size > limits.max_skill_size_bytes:
                raise LimitExceededError(f"Skill directory '{skill_dir.relative_to(root)}' size {skill_size:,} bytes exceeds limit of {limits.max_skill_size_bytes:,} bytes")
```
**边界是 `>` 而非 `>=`**：恰好 3,221,225,472 字节、恰好 10,000 个文件**通过**。**单文件没有独立大小上限**（除 YAML 50 MiB 与 skill 目录 50 MiB）。

#### （5）YAML 加载与 `!include`

| 条件 | 异常 | 出处 |
| :--- | :--- | :--- |
| 顶层不是 mapping | `SubmissionValidationError` | `yaml_loader.py:315-319` |
| 单 YAML > 50 MiB | `LimitExceededError` | `yaml_loader.py:295-299` |
| YAML 节点数 > `max(max_bytes//8, 10_000)` | `LimitExceededError` | `yaml_loader.py:140-153` |
| 展开体积 / 节点数 > 50,000（anchor bomb） | `LimitExceededError` | `yaml_loader.py:81-120` |
| 锚点密集时 `max_expanded = min(max_bytes, max(file_size*20, 65_536))` | `LimitExceededError` | `yaml_loader.py:310-313` |
| `!include` 扩展名 ∉ `{.md,.txt,.yaml,.yml}` | `SubmissionValidationError` | `yaml_loader.py:24-29` |
| 嵌套深度 > 10 | `SubmissionValidationError` | `yaml_loader.py:195-198` |
| included 文件不存在 / 逃逸 / 符号链接 / 累计超限 | `PathTraversalError` / `SubmissionValidationError` / `LimitExceededError` | `yaml_loader.py:47-78, 177-190` |
| YAML 语法错误 | **原生 `yaml.YAMLError`**（不是 `SubmissionError`） | `compiler.py:113` 文档声明 |

#### （6）YAML 结构 / 未知字段 / schema 校验失败

- **所有模型 `extra="forbid"`**：`schema.py:54`（`SubAgentRef`）、`:95`（`AgentToolRef`）、`:135`（`AgentToolEntry`）、`:166`（`ThinkingConfig`）、`:201`（`GenerateContentConfig`）、`:246`（`_BaseAgentFields`，4 种 agent 配置都继承）。→ **任何拼错的键（`instrution`、`sub_agent`、`max_iteration`…）都是硬失败。**
- 入口 `compiler.py:136-140`：
  ```python
  try:
      config = SandboxedAgentConfig.model_validate(raw_config)
  except Exception as e:  # noqa: BLE001
      handle_schema_validation_error(e, context_desc="config")
  ```
  → `paths.py:213-214` `raise SubmissionSchemaError(f"Submission schema validation failed: {e}")`
- 判别式 union（`schema.py:373-396`）：`agent_class` 取 `v.get("agent_class") or "LlmAgent"`；未知值 / 非 dict → 失败。合法值 4 种：`LlmAgent` / `SequentialAgent` / `ParallelAgent` / `LoopAgent`。
- **LlmAgent 的 `instruction` 必填**（`schema.py:279-281`）。`include_contents` 只接受 `"default" | "none"`（`schema.py:283`）。
- schema 硬下限（`schema.py`）：`temperature ge=0.0`（`:203`）、`top_p 0..1`（`:204`）、`top_k ge=1`（`:205`）、`max_output_tokens ge=1`（`:206`）、**`thinking_budget ge=1`（`:168`）**、`max_iterations ge=1`（`:360`）；bool / NaN / inf 一律拒（`:145-152, 172-175, 214-226, 362-365`）。
- **被设计性排除、写了就报错的 ADK 字段**：`tools`、`system_instruction`、`http_options`、`safety_settings`、`response_schema`（`schema.py:184-186, 201-212`）。

#### （7）路径逃逸 / 绝对路径 / 符号链接

`paths.py:39-56`（逐字）：
```python
    raw = str(path).strip()
    if not raw:
        return
    ctx_suffix = f" {context}" if context else ""

    # Check for absolute path indicators (POSIX and Windows)
    if (
        raw.startswith(("/", "\\"))
        or bool(_WINDOWS_DRIVE_PATTERN.match(raw))
        or Path(raw).is_absolute()
    ):
        raise PathTraversalError(f"Path traversal attempted{ctx_suffix}: {raw}")

    # Check for '..' components across all path separators
    normalized_parts = raw.replace("\\", "/").split("/")
    if ".." in normalized_parts:
        raise PathTraversalError(f"Path traversal attempted{ctx_suffix}: {raw}")
```

`discovery.py:99-108`（**提交目录内任何符号链接都直接拒**，哪怕指向内部文件）：
```python
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise SubmissionValidationError(
                f"Symlinks are not permitted: {p.relative_to(root)}"
            )
        if p.is_file():
            all_files.append(p)
            total_size += p.stat().st_size
```

子 agent / AgentTool 的 `config_path` 走 `context.py:98-124` → `validate_sandboxed_path(..., must_exist=True, allow_symlinks=False, allowed_extensions={".yaml",".yml"})`；找不到 → `SubmissionValidationError("Sub-agent config not found: ...")`（`paths.py:150-161`）。`paths.py:102-161` 还检查**父目录链上任何符号链接**（`for parent in raw_target.parents`）。

#### （8）引用不存在的名字

| 引用对象 | 触发点 | 异常 |
| :--- | :--- | :--- |
| tool 名 | `registry.py:72-75`（`ToolRegistry._error_cls = ToolNotFoundError`，`registry.py:134`）；调用点 `resolvers/tools.py:64-65` | `ToolNotFoundError` |
| model 别名 | `registry.py:161`（`_error_cls = ModelNotFoundError`）；调用点 `resolvers/models.py:59,78` | `ModelNotFoundError` |
| adapter 名 | `resolvers/models.py:46-53`：`if not ctx.adapter_manifest or config.adapter not in ctx.adapter_manifest.adapters: raise AdapterNotFoundError(config.adapter, available=available)` | `AdapterNotFoundError` |
| adapter 无 base model | `resolvers/models.py:54-58`：`if not config.model: raise SubmissionValidationError(f"Agent '{config.name}' specifies adapter '{config.adapter}' without a base model alias.")` | `SubmissionValidationError` |
| callback 名 / 位置不符 | `registry.py:278-294`；调用点 `resolvers/callbacks.py:90-92` | `CallbackNotFoundError` |
| skill 名（有 registry） | `resolvers/tools.py:170-182` | `SkillNotFoundError` |
| skill 目录（无 registry） | `resolvers/tools.py:185-192`（不存在）/ `:213-221`（加载失败 → `Failed to load skill '{ref}': {e}`）/ `:261-264`（`SkillToolset` `ValueError`） | `SubmissionValidationError` |
| 子 agent 配置 | `builders/sub_agents.py:57-65` | `PathTraversalError` / `SubmissionValidationError` / `SubmissionSchemaError` |

> ⚠️ **重要 nuance**：`resolvers/callbacks.py:83-85`
> ```python
>     kwargs: dict[str, Any] = {}
>     if ctx.callback_registry is None:
>         return kwargs
> ```
> **`callback_registry=None` 时，配置里写的任何 callback 名字都不校验（静默丢弃）。** 只有组织者传入 registry 时才报错。

#### （9）adapter 规则

- **目录固定 `<root>/adapters/`**，只有它下面的文件才算 adapter（`discovery.py:130-139`）：
  ```python
  adapters_dir = root / "adapters"
  adapter_files = [
      p for p in all_files
      if p.suffix.lower() in limits.adapter_extensions
      and adapters_dir.is_dir()
      and p.is_relative_to(adapters_dir)
  ]
  ```
- `adapters/` 不存在 → 返回空 manifest，**不算错误**（`discovery.py:333-334`）；是符号链接 → `PathTraversalError`（`:329-332`）；内部任何符号链接 → `PathTraversalError`（`:340-343`）。
- 排除非权重词干（`discovery.py:307-316`）：
  ```python
  _NON_ADAPTER_WEIGHT_STEMS: frozenset[str] = frozenset(
      {"training_args", "optimizer", "scheduler", "scaler", "rng_state", "trainer_state"}
  )
  ```
- **重名冲突**：根层同名 stem → `SubmissionValidationError(f"Adapter name collision at root level: {info.name!r}")`（`:368-371`）；子目录消歧后仍冲突 → `SubmissionValidationError("Adapter name collision after disambiguation: ...")`（`:421-425`）。
- **PEFT 目录合并**（`:374-400`）：`(p.parent/"adapter_config.json").is_file() or p.stem == "adapter_model" or p.stem.startswith("adapter_model-")` → 同目录文件合成一个 adapter，优先 `adapter_model.safetensors`。
- **服务端附加约束**：adapter 名必须匹配 `^[a-zA-Z0-9_.-]+$`，否则 `SubmissionValidationError`（`server.py:58, 728-732`）→ 文件名含空格 / 中文会在这里被拒。

#### （10）生成参数越界

`GenerationConstraints`（`swegemma/config.py:59-67`）：
```python
gen_constraints = GenerationConstraints(
    allowed_fields=None,                       # 全放开
    max_output_tokens=NumericRange(1, 32768),
    thinking_budget=NumericRange(0, 32768),
    defaults={'max_output_tokens': 16384, 'thinking_config': {'thinking_budget': 4096}},
)
```

| 参数 | 声明约束 | schema 硬下限 | **实际接受区间** | 默认注入值 |
| :--- | :--- | :--- | :--- | :--- |
| `max_output_tokens` | `NumericRange(1, 32768)` | `ge=1`（`schema.py:206`） | **1 – 32768** | **16384** |
| `thinking_config.thinking_budget` | `NumericRange(0, 32768)` | **`ge=1`（`schema.py:168`）** | **1 – 32768**（**0 会在 schema 层就被 `SubmissionSchemaError` 毙掉**，`NumericRange` 的 0 下限永不生效） | **4096** |
| `temperature` | 无 | `ge=0.0` | ≥0，无上限 | — |
| `top_p` | 无 | `0.0 – 1.0` | 0 – 1 | — |
| `top_k` | 无 | `ge=1` | ≥1 | — |
| `seed` | 仅有限数 | `int` | 任意有限 | — |
| `presence_penalty` / `frequency_penalty` | 无 | 有限数 | 任意有限 | — |
| `stop_sequences` | 不限（`max_stop_sequences=None`） | `list[str]` | 不限 | — |
| `response_mime_type` | 不限 | `str` | 不限 | — |

校验逻辑 `limits.py:340-371`（逐字）：
```python
        # 1. Check each set field against allowed_fields
        if self.allowed_fields is not None:
            for key, val in config_dict.items():
                if val is not None and key not in self.allowed_fields:
                    raise SubmissionValidationError(
                        f"Agent '{agent_name}': generation parameter "
                        f"'{key}' is not allowed. "
                        f"Allowed parameters: {allowed_str}"
                    )

        # 2. Check numeric range constraints and finite non-bool types
        for field_name in _RANGE_CONSTRAINED_FIELDS | {"seed"}:
            if field_name in config_dict and config_dict[field_name] is not None:
                val = config_dict[field_name]
                if (isinstance(val, bool) or not isinstance(val, (int, float))
                        or math.isnan(val) or math.isinf(val)):
                    raise SubmissionValidationError(
                        f"Agent '{agent_name}': {field_name}={val!r} is not a valid finite number"
                    )
                if field_name in _RANGE_CONSTRAINED_FIELDS:
                    range_constraint: NumericRange | None = getattr(self, field_name)
                    if range_constraint is not None:
                        range_constraint.check(val, field_name, agent_name)
```

**未显式配置也会注入 defaults**（`resolvers/generation.py:36-58`）→ **每个 LlmAgent 实际都带 `max_output_tokens=16384` + `thinking_budget=4096`**。

#### （11）循环 / 递归 / 深度 / 数量

```python
# builders/workflows.py:124-131
    max_iter = config.max_iterations
    if max_iter is None:
        max_iter = ctx.limits.max_loop_iterations
    elif max_iter > ctx.limits.max_loop_iterations:
        raise LimitExceededError(
            f"Agent '{config.name}': max_iterations={max_iter} exceeds "
            f"limit of {ctx.limits.max_loop_iterations}"
        )
```
```python
# builders/sub_agents.py:42-48
    ctx.depth += 1
    try:
        if ctx.depth > ctx.limits.max_sub_agent_depth:
            raise LimitExceededError(
                f"Sub-agent nesting too deep: {ctx.depth} "
                f"(max {ctx.limits.max_sub_agent_depth})"
            )
```
`resolvers/tools.py:93-101`（`agent_tool` **也计入同一 depth 计数器**）；`compiler.py:225-229`（`agent_count > max_agents` → `LimitExceededError`）；`context.py:142-153`（instruction 单/累计）；`resolvers/tools.py:153-158`（累计 skills）。

> ⚠️ **无环检测**：A 引用 B、B 引用 A 会一直递归，直到撞上 `max_agents=500` 或 `max_sub_agent_depth=50`。
> ⚠️ **skill 的 `SKILL.md` 文本也计入 instruction 预算**（`resolvers/tools.py:223-238`）。

#### （12）服务端（`server.py`）能导致的拒绝

```python
# server.py:728-732
                if not _VALID_ADAPTER_NAME_RE.match(name):
                    raise SubmissionValidationError(
                        f"Invalid adapter name '{name}': must match ^[a-zA-Z0-9_.-]+$"
                    )
```
（`_VALID_ADAPTER_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")`，`server.py:58`）
- `TransformersServer` 一次只允许 **1** 个 LoRA，否则 `ServerStartupError`（`server.py:404-412, 505-513`）。
- 健康检查超时 / 进程提前退出 → `ServerStartupError`（`server.py:305-332`）。

### 6.4 submission 目录的发现逻辑

**两层发现，用途不同：**

**① Kaggle 打包期**（`swegemma/submission.py:35-104`，`generate_standard_submission`）：
```python
    for d in [submission_dir, '/kaggle/working', '/kaggle/tmp']:   # 搜索路径顺序
        ...
        for pattern in ('**/agent.yaml', '**/root_agent.yaml'):
            dir_candidates.extend(glob.glob(os.path.join(search_dir, pattern), recursive=True))
        if dir_candidates:
            dir_candidates.sort(key=lambda p: (
                len(Path(p).parts),                            # ① 路径段数最少（最浅）
                0 if Path(p).name == 'agent.yaml' else 1,      # ② agent.yaml 优先
                p,                                             # ③ 字典序
            ))
            agent_yamls.extend(dir_candidates)
    ...
    agent_dir = os.path.dirname(agent_yamls[0])                # 取全局第一个
```
- **搜索顺序**：`submission_dir` → `/kaggle/working` → `/kaggle/tmp`，第一个命中的目录胜出
- **0 个 → `ParticipantVisibleError`**（会显示在 Kaggle UI 给参赛者）
- **只认 `agent.yaml` / `root_agent.yaml` 两个名字** —— `agent.yml` / `root_agent.yml` 在这里**找不到**（与编译器逻辑不同）
- 产物：把 `agent_dir` 写进 `submission.parquet` 的 `prediction` 列
- `get_eval_root()`（`submission.py:18-32`）：`KAGGLE_EVAL_ROOT` → `/kaggle/input/competitions/gemma-4-developer-agent` → `/kaggle/input/gemma-4-developer-agent` → `/kaggle/input/datasets/metric/swegemma-evaluation` → `data`

**② 编译期**（`adk_submission/discovery.py:60-177` `validate_directory`）：把 `submission_dir` resolve 成 root，然后按 §6.1 的 8 步顺序校验，`find_root_config` 定根。

**"根"的完整定义**：提交目录**顶层**的那一个规范名 YAML（`agent.yaml` > `root_agent.yaml` > 顶层唯一 YAML）。所有子 agent 路径、`!include` 路径、skill 路径都必须解析到 `root_dir` 之内。**adapter 只认 `<root>/adapters/`**。

### 6.5 一页速查：会被拒的清单

| # | 条件 | 异常 | 出处 |
| :-- | :--- | :--- | :--- |
| 1 | 目录不存在 / 不是目录 | `SubmissionValidationError` | `discovery.py:91-94` |
| 2 | 目录树内**任何**符号链接 | `SubmissionValidationError` / `PathTraversalError` | `discovery.py:101-105, 201-204, 329-332, 340-343` |
| 3 | 无根配置 / 顶层多个 YAML 且无规范名 | `SubmissionValidationError` | `discovery.py:240-251` |
| 4 | 扩展名 ∉ 7 种白名单（含无扩展名文件） | `SubmissionValidationError` | `discovery.py:121-127` |
| 5 | 文件数 > 10000 / 总大小 > 3 GiB / YAML > 1000 个 / 单 YAML > 50 MiB / skill 目录 > 50 MiB | `LimitExceededError` | `discovery.py:110-165`；`yaml_loader.py:295-299` |
| 6 | `!include` 深度 > 10 / 扩展名不符 / 不存在 / 累计超限 / anchor bomb | `SubmissionValidationError` / `LimitExceededError` | `yaml_loader.py:24-29, 81-120, 155-216` |
| 7 | YAML 顶层非 mapping / 语法错误 | `SubmissionValidationError` / `yaml.YAMLError` | `yaml_loader.py:315-319` |
| 8 | 未知字段（`extra="forbid"`）/ 缺 `instruction` / 未知 `agent_class` / 数值越界 / 写了 `tools`·`system_instruction`·`safety_settings`·`response_schema` | `SubmissionSchemaError` | `schema.py:54,95,135,166,201,246,279-281,373-396`；`compiler.py:137-140` |
| 9 | `config_path` / `skills` 含 `..` 或绝对路径，或解析出根目录 | `PathTraversalError` | `paths.py:39-56, 130-147`；`schema.py:61-76, 103-118, 305-322` |
| 10 | 未知 tool / model / adapter / callback / skill 名；adapter 无 base model | 各自 `*NotFoundError` / `SubmissionValidationError` | `registry.py:72-75, 278-294`；`resolvers/models.py:46-58`；`resolvers/tools.py:170-182` |
| 11 | adapter 用 `.bin`/`.pt`/`.pth`/`.gguf`/`.ggml`、放错目录、重名、名字不匹配 `^[a-zA-Z0-9_.-]+$` | `SubmissionValidationError` | `discovery.py:122-127, 133-139, 368-371, 421-425`；`server.py:729-732` |
| 12 | 声明 0 个或多个 distinct base model | `ParticipantVisibleError` | `swegemma/models/discovery.py:107-119` |
| 13 | `max_output_tokens` ∉ [1,32768]；`thinking_budget` ∉ **[1**,32768]；`top_p` ∉ [0,1]；`temperature` < 0；`top_k` < 1；bool / NaN / inf | `SubmissionValidationError` / `SubmissionSchemaError` | `config.py:61-62`；`limits.py:340-438`；`schema.py:168,203-206` |
| 14 | agent 数 > 500 / 深度 > 50 / `max_iterations` > 500 / 单 instruction > 1e6 / 累计 > 1e7 / 累计 skills > 1000 | `LimitExceededError` | `compiler.py:225-229`；`sub_agents.py:42-48`；`tools.py:93-101, 153-158`；`workflows.py:124-131`；`context.py:142-153` |
| 15 | 本地服务起不来 / 健康检查超时 / Transformers 多 LoRA | `ServerStartupError` | `server.py:305-332, 404-412, 505-513` |

**异常类型层级**（`errors.py`）：`SubmissionError` → `SubmissionValidationError(ValueError)` → `LimitExceededError` / `PathTraversalError` / `SubmissionSchemaError`；并列的 `ToolNotFoundError`、`ModelNotFoundError`、`AdapterNotFoundError`、`CallbackNotFoundError`、`SkillNotFoundError` 直接继承 `SubmissionError`（**不是** `SubmissionValidationError`）；另有 `ServerStartupError`（`errors.py:272-290`）。

### 6.6 `adk_submission/server.py` 是什么（与本地复现强相关）

**是本地推理服务进程管理器**（docstring `server.py:1-27`），**确实会拉起本地 vLLM / Transformers 子进程**：

```python
# server.py:665-683  VllmServer.build_cmd
        cmd = [
            sys.executable, "-m", "vllm.entrypoints.openai.api_server",
            "--model", self.config.model,
            "--host", self.config.host,
            "--port", str(self.config.port),
            "--max-model-len", str(self.config.max_model_len),
            "--dtype", self.config.dtype,
            "--gpu-memory-utilization", str(self.config.gpu_memory_utilization),
        ]
```
```python
# server.py:593-617  TransformersServer.build_cmd（节选）
        if is_v5:
            cmd = [sys.executable, "-m", "transformers.cli.transformers", "serve",
                   self.effective_model_path, "--host", self.config.host,
                   "--port", str(self.config.port)]
        else:
            cmd = [sys.executable, "-m", "transformers.commands.transformers_cli", "serve",
                   "--model", self.effective_model_path, "--host", self.config.host,
                   "--port", str(self.config.port)]
```

| 项目 | 值 | 出处 |
| :--- | :--- | :--- |
| 类 | `BaseInferenceServer`(162)、`TransformersServer`(485)、`VllmServer`(653) | `server.py` |
| 工厂 | `spawn_server(backend=...)`(771)、`spawn_vllm_server`(755)、`spawn_transformers_server`(739) | `server.py` |
| 配置 | `VllmConfig`(94)、`TransformersConfig`(61) | `server.py` |
| 默认 host:port | **`127.0.0.1:8000`** | `server.py:81-82, 127-128` |
| base_url | `http://{host}:{port}/v1` | `server.py:183-186` |
| 健康检查 | `http://{host}:{port}/health`，轮询至 200 或 `startup_timeout` | `server.py:188-191, 242-253, 293-332` |
| 默认模型路径 | **无默认值**，`model: str` 必填构造参数 | `server.py:80, 126` |
| vLLM 默认超参 | `max_model_len=32768`、`dtype="auto"`、`gpu_memory_utilization=0.90`、`enable_lora=True`、`max_loras=8`、`max_lora_rank=128`、`tool_call_parser="hermes"`、`reasoning_parser=None`、`startup_timeout=600`、`tensor_parallel_size=1` | `server.py:129-146` |
| 注册表工厂 | `create_model_registry(aliases=None, model_prefix="hosted_vllm/", api_key="EMPTY")` | `server.py:379-470` |

```python
# server.py:457-465
            for alias, model_name in model_aliases.items():
                registry.register(alias, LiteLlm(
                    model=_format_model_id(model_name),
                    api_base=self.base_url,
                    api_key=api_key or "EMPTY",
                ))
```

**能否指向远程 OpenAI 兼容 API？——没有专门的开关或环境变量。**

- `server.py` 里的 `os.environ` 只有三处 `setdefault`：`LITELLM_LOCAL_MODEL_COST_MAP`、`LITELLM_TELEMETRY`（`server.py:199-200`）、`LITELLM_LOG`（`server.py:438-440`）——**都是给 LiteLLM 降噪的，不涉及 endpoint 配置**。
- 唯一可行手法是**隐式**的：`api_base` 完全来自 `self.base_url ← config.host/config.port`（`server.py:184-186, 462`）。所以可以
  ```python
  cfg = VllmConfig(model="<占位>", host="<远程主机>", port=<远程端口>)
  server = VllmServer(cfg)                        # 不调用 start()，不进入 with 上下文
  models = server.create_model_registry("gemma-4-31b-it")   # api_base = http://<远程>/v1
  ```
  但这属于**绕过生命周期管理**的用法，`spawn_*` 没有 `skip_start` / `remote` 之类的标志。
- **本赛事真正的「远程/代理」通路不在 `server.py`，而在 `swegemma`**（见 §7.4）。
- **交叉验证**：`grep -rn "adk_submission.server\|VllmServer\|spawn_vllm\|create_model_registry" swegemma-0.2.7/` → **0 命中**。即 **vendored swegemma 全程不 import `server.py`**，本仓库 harness 假定端点已由外部（Kaggle metric）启动或为远程代理。

---

## 6.7 §6 与 `HARNESS_README.md` 的差异

| README 说法 | 源码事实 |
| :--- | :--- |
| `:94` 「zero → `MissingRootConfigError`；more than one → `MultipleRootConfigsError`」 | **这两个类不存在**（`grep` 无命中）；实为 `SubmissionValidationError`（`discovery.py:241-251`）。且「more than one」**仅在顶层无规范名时**成立 —— `agent.yaml` + `root_agent.yaml` 并存**不报错** |
| `:144` `thinking_budget` 范围 `1–32768` | 结论正确，但机制是 **schema `ge=1`（`schema.py:168`）覆盖了** `NumericRange(0, 32768)`（`config.py:62`）|
| `:140` 扩展名白名单 7 种 | 与 `config.py:20-30` 一致；**但 README 没提它还隐含拒绝所有无扩展名文件**（库默认白名单含 `""`，赛事集合不含） |
| `:194` 「VllmServer … `tool_call_parser='gemma4'`, `reasoning_parser='gemma4'`」 | `server.py` 的字段默认是 **`tool_call_parser="hermes"`、`reasoning_parser=None`**；`gemma4` 是 metric 侧传入的参数，不是库默认值 |
| `:121` LoopAgent `max_iterations`「default 500, bounded to 1..500」 | 与 `workflows.py:124-131` + `schema.py:360`(`ge=1`) 一致 ✅ |
| `:32` 说 `adk-submission`「manages the local `VllmServer` and `TransformersServer`」 | 属实（`server.py` 确实管），但 **swegemma CLI 路径完全不调用**它 |

---

## 7. 本地可复现性判定

**测试机环境（实测）**：Apple M4 / arm64 / 24 GiB RAM（`hw.memsize = 25769803776`）/ Python 3.13.5 (Anaconda) / **无 NVIDIA GPU** / Docker.app 已装但 **daemon 未运行**。

### 7.1 结论表

| 环节 | 能否本地跑 | 依据 |
| :--- | :--- | :--- |
| `swegemma` 包导入 | ❌ **当前不能** | `swegemma/__init__.py:6` → `adk_eval_core` → `google.adk` **未安装**（实测 `ModuleNotFoundError: No module named 'google.adk'`） |
| 任务加载 / 指标聚合（`load_tasks`、`resolution_rate`） | ✅ 纯 Python，无需 GPU | `models/task.py:218-233`、`runner.py:31-36` |
| `--sandbox subprocess` 后端 | ✅ **代码路径完整，可替代 docker** | 见 §7.2 |
| `--sandbox docker` 后端 | ⚠️ 需启动 Docker daemon + 自建/拉取 `swebench-sandbox:latest` 镜像 | `sandbox/docker.py:36-40` `docker.from_env()` |
| Phase 1 agent loop | ❌ **缺 snapshots**（本地无任何 `*.tar.gz`/`*.tgz`） | `evaluate.py:274-295` |
| Phase 2 `verify_task` | ❌ **缺 snapshots**；且需能 `pip install` 仓库依赖（沙箱离线） | 同上 + `install_test_dependencies` |
| `--skip-agent-patch`（只跑 Phase 2 baseline） | ❌ 仍缺 snapshots | `evaluate.py:300-303` |
| vLLM 本地服务 | ❌ **不可行**（无 CUDA；M4 只能 CPU/MPS，31B w4a16 在 24 GB 上基本不现实） | — |
| 远程 OpenAI 兼容 API | ✅ **可行，代码里有现成注入点** | 见 §7.4 |
| graph / embedding 工具 | ❌ 本地 `data/graphs/` 不存在，`data/embeddings/` 6 个文件里 4 个 0 字节 | 见 §4.5 |

### 7.2 `sandbox/subprocess.py` 能否替代 docker？

**能，代码路径是完整的、被官方支持的**（`cli.py:54-59` 的 `--sandbox {docker,subprocess}`，`config.py:98` 注释 `'subprocess' (Kaggle/notebooks)`）。`SubprocessManager`（`sandbox/subprocess.py:30-559`）实现了完整的 `BaseSandbox` 协议：`start/stop/exec/copy_to/copy_from/write_file/read_file/get_sandbox`。

关键适配点（都已正确处理）：

| 机制 | 实现 |
| :--- | :--- |
| **`/workspace`、`/tmp`、`/wheels`、`/usr/local/bin` 路径翻译** | `exec()` 用正则把命令里的这些绝对路径替换成 `tmpdir/swegemma_sandbox_<id>_xxx/{workspace,tmp,wheels,venv/bin}`（`subprocess.py:432-481`）；`copy_to`/`copy_from` 有对称的映射表（`:178-232, 260-309`） |
| **隔离 venv** | 每个 sandbox 建一个 `venv`，`system_site_packages=True`（默认），并写 `_host_env.pth` 指向宿主 `site-packages`（`:389-400`），保证宿主已装的包（如 pytest）可用 |
| **环境净化** | `build_sanitized_env()` 只透传 `_SAFE_ENV_KEYS`（PATH/LANG/LC_ALL/TERM/USER/LOGNAME/SYSTEMROOT/LD_LIBRARY_PATH/TMPDIR/TEST_TMPDIR），强制 `PYTHONNOUSERSITE=1`（`adk_eval_core/sandbox/subprocess_sandbox.py:26-56`） |
| **`install_editable_package`** | **对 `SubprocessManager` 直接 return**（`container_setup.py:512-513`） |
| **`install_test_dependencies`** | **对 `SubprocessManager` 直接 return**（`container_setup.py:529-530`）→ **不需要 `sandbox/setup.py`** |
| **`disable_test_runners_in_sandbox`** | **对 `SubprocessManager` 跳过**（`container_setup.py:980-983`，"to protect host environment"） |
| **JUnit XML 校验** | `verify_task` 的 `is_real_sandbox` 白名单**包含 `'SubprocessManager'`**（`verification.py:514-519`）→ 第二道门照样执行 |
| **`setup_container_wheels`** | 无 `extract_archive_to_container` 属性 → 走 `resolve_wheels_dir` + `copy_to(..., '/wheels')`（`container_setup.py:407-413`） |

**已知本地缺口（不是代码问题，是数据问题）：**

1. **snapshots 缺失** —— `data/` 下**没有任何 `*.tar.gz` / `*.tgz`**。`swegemma eval --snapshots-dir` 是必填参数，`evaluate.py:274-295` 找不到就返回 `Snapshot file not found`，任务全部 0 分。这是**真正的硬阻塞**。
2. **wheels 缺失** —— `resolve_wheels_dir`（`container_setup.py:65-86`）遍历 `data/wheels`、`wheels`、`/wheels`、`/tmp/wheels` 等，本地都不存在 → `setup_container_wheels` 静默跳过。只有宿主 Python 3.13 环境里已装的包能用。
3. **`sandbox/setup.py`**：`data/sandbox/setup.py` **存在**，会被 `resolve_sandbox_setup_script` 命中（`container_setup.py:30-31`，因为 `tasks_path.parent/'sandbox'/'setup.py'`）。但 subprocess 模式下 `install_test_dependencies` 提前 return，所以**不会执行它**。
4. **venv + Python 3.13 + macOS arm64**：`venv.create(..., with_pip=True, symlinks=True/False)` 有 fallback 链（`subprocess.py:331-387`），Anaconda Python 一般 OK。注意宿主是 **arm64/macOS**，而任务快照里的仓库是 Linux 生态；`.whl` 兼容性检查函数 `_is_wheel_compatible_py313` 明确检查的是 **Linux x86_64**（`container_setup.py:89-90`），在 Mac 上会判不兼容。

### 7.3 `models/registry.py` 是否强制要求 vLLM 本地服务？

**不强制。** 三点证据：

1. `setup_gemma_model_registry()`（`models/registry.py:69-110`）返回的是 `ModelRegistry`，里面每个条目都是 **`LiteLlm(model=..., api_base=endpoint, api_key=key, num_retries=...)`**（`:149-157`）。`LiteLlm` 走的是 **OpenAI 兼容 HTTP 客户端**，对 endpoint 的实现毫无假设。
2. base URL 默认是 `'http://localhost:8000/v1'`（`:100`），但这只是**默认串**，不是强制校验；换成任何 OpenAI 兼容 URL 都能工作。
3. 模型别名表（`:115-132`）是**静态字符串映射**，`'gemma-4-31b-it-qat-w4a16-ct' → 'openai/gemma-4-31b-it-qat-w4a16-ct'`，不会探测服务是否存在。（唯一的特例逻辑：`served_model` 参数会把**所有**别名重定向到同一个 target，见 `:134-147`。）

vLLM 的启动完全发生在 `adk_submission/server.py` 的 `VllmServer` / `TransformersServer`（需要 CUDA；`server.py:77,123` 有 `nvidia_lib_dir: str = "/usr/local/lib64"` 默认值）。**`swegemma eval` 的 CLI 路径不会调用它** —— 只调用 `setup_gemma_model_registry()`（`cli.py:140`）。

### 7.4 注入点：把 agent 接到远程 OpenAI 兼容 API

**有，而且是多个层次。** 具体文件与函数：

**注入点 ①（最省事，零代码改动）—— 环境变量**

`models/registry.py:94-110`（函数 `setup_gemma_model_registry`，被 `cli.py:140` 调用）：
```bash
export OPENAI_BASE_URL="https://your-endpoint.example.com/v1"
export OPENAI_API_KEY="sk-xxxx"
# 或 MODEL_PROXY_URL / LITELLM_API_BASE / LOCAL_INFERENCE_URL
swegemma eval --tasks ... --snapshots-dir ... --results-dir ... --submission-dir ... --sandbox subprocess
```
优先级：`MODEL_PROXY_URL` > `LITELLM_API_BASE` > `LOCAL_INFERENCE_URL` > `OPENAI_BASE_URL` > `http://localhost:8000/v1`。
Key 优先级：`MODEL_PROXY_API_KEY` > `LITELLM_API_KEY` > `LOCAL_API_KEY` > `OPENAI_API_KEY` > `'EMPTY'`。
另支持项目根 `.env` 文件（`models/registry.py:14`、`cli.py:19`，`load_dotenv(override=False)` —— **不覆盖已有的环境变量**）。

**注入点 ②（最灵活）—— `--models-yaml`**

`cli.py:84-89` → `setup_gemma_model_registry(models_yaml_path=args.models_yaml)` → `models/registry.py:178-197`：
```python
yaml_path = Path(models_yaml_path).resolve() if models_yaml_path else None
if yaml_path and yaml_path.exists():
    from adk_submission.yaml_loader import load_yaml
    data = load_yaml(yaml_path, yaml_path.parent) or {}
    defined_models = data.get('models', {})
    for model_alias, cfg in defined_models.items():
        model_name = cfg.get('path') or f'openai/{model_alias}'
        model_endpoint = normalize_api_endpoint(cfg.get('api_base')) or endpoint
        model_key = cfg.get('api_key') or key
        models.register(model_alias, LiteLlm(model=model_name, api_base=model_endpoint, api_key=model_key, num_retries=num_retries))
```
即可以写一个 `models.yaml`：
```yaml
models:
  gemma-4-31b-it-qat-w4a16-ct:
    path: openai/gemma-4-31b-it-qat-w4a16-ct    # 或任何远程服务暴露的 model 名
    api_base: https://your-endpoint.example.com/v1
    api_key: sk-xxxx
```
⚠️ **注意覆盖顺序 bug**：`gemma_configs` 的 16 个别名（`:144-157`）在**前**注册，`models.yaml` 在**后**注册（`:185-197`）。`ModelRegistry.register` 若为覆盖语义则 YAML 生效；若为「已存在则跳过」则 YAML 不生效。**这一条需要看 `adk_submission/registry.py` 的 `ModelRegistry.register` 实现确认**（本次分析未展开）——稳妥做法是同时设置环境变量，或在 YAML 里用**新的别名**并在 `agent.yaml` 里引用它。

**注入点 ③（编程式）—— `EvalConfig.models`**

`Evaluator.__init__(config)` 直接用 `config.models`（`evaluate.py:60-79`），而 `run_agent_sandbox` 把它传给 `compile_submission(model_registry=config.models, ...)`（`agent_runner.py:334-346`）。所以任何 Python 脚本都可以：
```python
from swegemma.models import setup_gemma_model_registry
from swegemma import EvalConfig, Evaluator

models = setup_gemma_model_registry(
    api_base="https://your-endpoint.example.com/v1",
    api_key="sk-xxxx",
    num_retries=5,
)
config = EvalConfig(
    tasks_path=..., snapshots_dir=..., results_dir=..., submission_dir=...,
    models=models,
    sandbox='subprocess',      # 不用 docker
    max_time_minutes=30,
    max_tool_calls=200,
    max_turns=200,
    timeout_seconds=600,
    task_ids=['fastapi_15661'],
    display_mode='single',
)
import asyncio; asyncio.run(Evaluator(config).run())
```

**注入点 ④（模型名归一化）—— `normalize_api_endpoint`**

`models/registry.py:17-33` 会自动给 Kaggle Model Proxy 风格 URL 补 `/openapi`：
```python
if url.endswith('/models'): return f'{url}/openapi'
if '/models' in url and not (url.endswith('/openapi') or url.endswith('/v1') or url.endswith('/genai')):
    return f'{url}/openapi'
return url
```
如果你的远程 endpoint 路径里恰好含 `/models` 且不以 `/v1` 结尾，**会被改写成 `/openapi`**——这是必须知道的坑。绕开办法：让 URL 以 `/v1` 结尾。

### 7.5 本地跑通的最小路径（明确建议）

**能做到：**
1. ✅ 用 `--sandbox subprocess` 跑通完整的两阶段流水线（不需要 Docker、不需要 NVIDIA GPU）
2. ✅ 用远程 OpenAI 兼容 API 当模型后端（环境变量或 `--models-yaml` 或 `config.models`）
3. ✅ 用 `--task-id <id>` 单任务调试，`--skip-agent-patch` 验证 Phase 2 判定逻辑

**做不到（缺数据，不是缺代码）：**
1. ❌ **真实任务评测**：本地没有 `snapshots/*.tar.gz`（129 个任务一个都跑不了 Phase 1/2）。`data/` 下 0 个 tarball
2. ❌ **Code Intelligence 工具有效性验证**：`data/graphs/` 不存在；`data/embeddings/` 6 个文件 4 个 0 字节
3. ❌ **本地 vLLM 推理**：无 CUDA、无 NVIDIA GPU

**因此：**
- **能做的**：把 `swegemma` 当作**判定逻辑 / prompt / 工具行为的规范实现**来对齐；用 `subprocess` 后端 + 远程 API + 自造的 mini snapshot 做**小规模自建任务**的端到端验证。
- **要拿真实分数**：必须回到 Kaggle 环境（4×L4 + 官方 snapshots + wheels + graph 数据）。
- **先决条件**：补装依赖 —— `google-adk`、`litellm`、`networkx`、`cachetools`、`numpy`、`pandas`、`python-dotenv`、`rich`、`docker`(可选)、`pytest`。当前宿主 Python 3.13 环境**连 `google.adk` 都没有**，`import swegemma` 就会失败。

---

## 8. 源码与 `HARNESS_README.md` 的差异清单（重要）

文档不是权威，代码才是。已核实的不一致：

| # | README 说法 | 代码实际 | 影响 |
| :-- | :--- | :--- | :--- |
| 1 | `README:591` 「resolved **iff** pytest 退出码 == 0」 | 还有第二道 JUnit XML 校验（`verification.py:507-542`） | 反作弊：`os._exit(0)` 打桩无效 |
| 2 | `README:586-588` pytest 命令行含 `-o norecursedirs=".* build dist venv"` | 实际命令**无此参数**（只写进 `pytest.ini`） | 命令行精确复现要对齐代码 |
| 3 | `README:449` edit exact 层「after normalizing `\r\n` → `\n`」 | 代码**没有 CRLF 归一化**（`workspace.py:212` 用 `newline=''`） | exact 层遇 CRLF 会 miss，靠 flexible 层 `rstrip()` 兜底 |
| 4 | `README:482` `resolve_node_name` 后缀分隔符「`.` 或 `/`」 | 实际是 **`.` 或 `;`**（`graph_utils.py:177`） | — |
| 5 | `README:557-558` 兜底 diff 命令 `git diff HEAD` | 实际 `git diff --binary _swegemma_baseline \|\| git diff --binary HEAD`（`tools/execution.py:53-56`、`agent_runner.py:765-767`） | `--binary` 会带上二进制补丁，patch 更大 |
| 6 | `README:539` 提到 `metric/scoring.py` 里的 `EventsCompactionConfig` / `ContextCacheConfig` | vendor 内 `EvalConfig.context_cache_config` / `events_compaction_config` **默认都是 `None`**（`config.py:116-117`），CLI **不设置它们** | 本地/自建跑不会有自动 compaction，长轨迹会爆 32k 上下文 |
| 7 | `README:523-533` 列 `SWE_*` 环境变量覆盖 | vendor 内**零实现**；由未分发的 `metric/scoring.py` 读取 | 只能通过 CLI 参数或 `EvalConfig` 控制预算 |
| 8 | `README:328` 称 `enable_sandbox_testing = True` 时「pytest/unittest 不 masked」 | 代码一致（`agent_runner.py:304-309` + `config.py:122`），但**prompt 段 5 只给一句话**，不告诉 agent 有 pytest | 若想省 token 可设 `enable_sandbox_testing=False`，prompt 会切到长版禁令文案 |
| 9 | `README:32` 说 `adk-submission`「manages the local `VllmServer` and `TransformersServer`」 | `cli.py` 路径**完全不调用** `server.py` | 本地/自建跑不会被强制起 vLLM |
| 10 | `README:562` 兜底提取在「lines 706–740」 | 实际在 `agent_runner.py:758-795` | 行号漂移 |
| 11 | `README:94` `MissingRootConfigError` / `MultipleRootConfigsError` | 这两个异常类**不存在**，实为 `SubmissionValidationError`；且 `agent.yaml` + `root_agent.yaml` 并存**不报错** | 见 §6.7 |
| 12 | `README:140` 扩展名白名单 7 种 | 数值一致，但**未提**它隐含拒绝所有无扩展名文件（`Makefile`/`LICENSE`/`.gitignore`） | 见 §6.2 |
| 13 | `README:194` VllmServer `tool_call_parser='gemma4'` | 库默认是 `tool_call_parser="hermes"`、`reasoning_parser=None` | 见 §6.6 |
| 14 | `README:517-533` 「budgets」表 | `--max-tool-calls` / `--max-turns` CLI 默认都是 `None`（无限），README 未明说「默认无限」 | 见 §2.1 |

---

## 9. 附：核心文件地图

| 关注点 | 文件 | 关键符号 |
| :--- | :--- | :--- |
| 判定闭环 | `swegemma/harness/verification.py` | `verify_task`, `_validate_junit_xml`, `_node_matches_requirement`, `_extract_test_functions_from_patch`, `_is_protected_test_or_config_path` |
| 编排 / 分数 | `swegemma/evaluate.py`、`swegemma/results.py`、`adk_eval_core/runner/runner.py` | `Evaluator.run`, `evaluate_task`, `save_results`, `EvaluationResult.resolution_rate` |
| 预算 | `swegemma/budget.py`、`swegemma/config.py`、`swegemma/context.py` | `EvaluationBudget`, `HarnessLimits`, `EvalConfig.__post_init__`, `SwegemmaContext.check_budget` |
| Prompt / nudge | `swegemma/harness/agent_runner.py` | `build_agent_prompt`, `run_agent_sandbox` |
| 图工具 | `swegemma/tools/graph.py`、`swegemma/graph/{graph_utils,retrieval_utils,embedding_utils}.py` | `search_similar_code`, `resolve_node_name`, `get_similar_nodes`, `embed` |
| 编辑 | `swegemma/edit.py`、`swegemma/tools/workspace.py`、`adk_eval_core/editing/edit.py` | `apply_replacement`, `_apply_exact_match`, `_apply_flexible_match`, `_apply_regex_match`, `apply_indentation` |
| 容器准备 | `swegemma/harness/container_setup.py` | `apply_patch_in_container`, `setup_workspace_test_config`, `setup_baseline_commit`, `install_test_dependencies`, `disable_test_runners_in_sandbox` |
| 沙箱 | `swegemma/sandbox/{docker,subprocess,base}.py` | `ContainerManager`, `SubprocessManager`, `sandbox_exec/start/stop` |
| 模型 | `swegemma/models/registry.py`、`swegemma/models/discovery.py` | `setup_gemma_model_registry`, `normalize_api_endpoint`, `validate_single_declared_model` |
