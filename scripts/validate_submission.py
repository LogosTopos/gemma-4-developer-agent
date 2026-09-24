#!/usr/bin/env python3
"""本地提交校验：在打包上传前拦住所有会导致拒收的格式问题。

复刻官方评测端 `compile_submission` 的校验链路，但不需要 GPU、不需要 Docker。
用的是官方分发的包（swegemma / adk_submission），所以校验规则与评测端一致。

用法:
    python3 scripts/validate_submission.py submission/
    python3 scripts/validate_submission.py submission/ --verbose
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _fail(stage: str, err: Exception) -> None:
    print(f"❌ [{stage}] {type(err).__name__}: {err}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("submission_dir", help="待校验的提交目录")
    ap.add_argument("--verbose", action="store_true", help="打印完整堆栈")
    ap.add_argument(
        "--clean",
        action="store_true",
        help="先删除 macOS/编辑器垃圾文件（.DS_Store 等会被直接拒收）",
    )
    args = ap.parse_args()

    sub = Path(args.submission_dir).resolve()
    if not sub.is_dir():
        print(f"❌ 不是目录: {sub}")
        return 2

    if args.clean:
        junk = [".DS_Store", "Thumbs.db", "desktop.ini"]
        removed = []
        for name in junk:
            for p in sub.rglob(name):
                p.unlink()
                removed.append(str(p.relative_to(sub)))
        if removed:
            print(f"🧹 已删除 {len(removed)} 个垃圾文件: {', '.join(removed[:5])}")
        else:
            print("🧹 无需清理")

    try:
        from adk_submission import (
            ModelRegistry,
            SubmissionLimits,
            ToolRegistry,
            compile_submission,
            validate_directory,
        )
        from swegemma.config import build_submission_limits
        from swegemma.models.discovery import validate_single_declared_model
    except ImportError as err:
        print(f"❌ 依赖未安装: {err}")
        print("   请在项目 .venv 中运行，或先安装 adk_submission / swegemma wheel")
        return 2

    limits, gen_constraints = build_submission_limits()
    problems = 0

    # ── 1. 目录结构：符号链接 / 大小 / 文件数 / 扩展名白名单 / 根配置唯一性 ──
    print("─" * 60)
    print("[1/4] 目录结构与硬闸门")
    try:
        info = validate_directory(sub, limits=limits)
        print("  ✅ 通过")
        if args.verbose:
            print(f"     {info}")
    except Exception as err:
        problems += 1
        _fail("目录校验", err)
        if args.verbose:
            traceback.print_exc()

    # ── 2. 单模型规则 ──
    print("[2/4] 单模型规则")
    declared_model: str | None = None
    try:
        declared_model = validate_single_declared_model(sub)
        print(f"  ✅ 唯一基座模型: {declared_model}")
    except Exception as err:
        problems += 1
        _fail("单模型规则", err)

    # ── 3. YAML 编译：语法 / !include / extra=forbid / 工具名 / 生成参数 ──
    print("[3/4] 编译为 ADK agent 树")
    try:
        model_registry = ModelRegistry()
        if declared_model:
            # 只为通过别名查找，不会真的发起推理
            model_registry.register(declared_model, f"openai/{declared_model}")
        # 内置 9 个工具的名字，允许提交引用
        builtin = [
            "run_command", "read_file", "write_file", "edit_file",
            "submit_patch", "get_status",
            "get_code_neighbors", "search_similar_code", "get_code_subgraph",
        ]
        tool_registry = ToolRegistry()
        for name in builtin:
            tool_registry.register(name, lambda **_: "{}")
        agent = compile_submission(
            submission_dir=sub,
            tool_registry=tool_registry,
            model_registry=model_registry,
            limits=limits,
            generation_constraints=gen_constraints,
        )
        print(f"  ✅ 编译成功: {type(agent).__name__}(name={getattr(agent, 'name', '?')})")
    except Exception as err:
        problems += 1
        _fail("编译", err)
        if args.verbose:
            traceback.print_exc()

    # ── 4. 打包前的额外检查（官方未覆盖但会踩的坑）──
    print("[4/4] 额外提醒")
    warnings: list[str] = []
    for p in sub.rglob("*"):
        if p.is_symlink():
            warnings.append(f"符号链接（会被拒收）: {p.relative_to(sub)}")
        elif p.is_file() and not p.suffix:
            warnings.append(f"无扩展名文件（会被拒收）: {p.relative_to(sub)}")
        elif p.is_file() and p.suffix not in limits.allowed_file_extensions:
            warnings.append(f"扩展名不在白名单: {p.relative_to(sub)}")
    total = sum(p.stat().st_size for p in sub.rglob("*") if p.is_file())
    print(f"  解压后总大小: {total / 1024 / 1024:.2f} MiB / 3072 MiB")
    if total > limits.max_total_size_bytes:
        warnings.append("总大小超过 3 GiB")
    if warnings:
        for w in warnings:
            print(f"  ⚠️  {w}")
    else:
        print("  ✅ 无额外问题")

    print("─" * 60)
    if problems:
        print(f"结果: ❌ {problems} 项校验失败")
        return 1
    print("结果: ✅ 全部校验通过，可以打包")
    return 0


if __name__ == "__main__":
    sys.exit(main())
