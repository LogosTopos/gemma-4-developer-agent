#!/usr/bin/env python3
"""本地端到端跑通验证：假 LLM + subprocess 沙箱 + 真实任务快照。

目的不是拿分，而是验证：
  提交包能被编译 → 沙箱能起 → 工具能被调用 → patch 能被抽取 → Phase 2 能执行。
"""
import os, sys, json
from pathlib import Path

os.environ.setdefault("OPENAI_BASE_URL", "http://127.0.0.1:8111/v1")
os.environ.setdefault("OPENAI_API_KEY", "EMPTY")

from swegemma.config import EvalConfig, build_submission_limits
from swegemma.evaluate import Evaluator
from swegemma.models.registry import setup_gemma_model_registry

TASK = sys.argv[1] if len(sys.argv) > 1 else "fastapi_11194"

models = setup_gemma_model_registry(api_base="http://127.0.0.1:8111/v1", api_key="EMPTY")
limits, gen = build_submission_limits()

cfg = EvalConfig(
    tasks_path=Path("data/tasks.jsonl"),
    snapshots_dir=Path("data/snapshots"),
    results_dir=Path("experiments/e2e"),
    submission_dir=Path("submission"),
    models=models,
    sandbox="subprocess",
    graph_dir="data/graphs",
    embeddings_dir="data/embeddings",
    task_ids=[TASK],
    max_time_minutes=3,
    max_tool_calls=20,
    max_turns=20,
    display_mode="single",
    limits=limits,
    generation_constraints=gen,
)
print(f"=== 开始本地端到端验证: {TASK} ===", flush=True)
import asyncio

result = asyncio.run(Evaluator(cfg).run())
print("=== 结果 ===", flush=True)
print(json.dumps(result, default=str, indent=2)[:3000])
