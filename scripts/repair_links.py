#!/usr/bin/env python3
"""修复 graphs/ 与 embeddings/ 里的 0 字节文件。

背景：这两个目录各 256 个文件，实际只有 127 个不同的 commit（129 任务中 2 组共享 commit）。
Kaggle 打包时硬链接退化成独立文件，每组只有一份活下来，其余变成 0 字节。
文件名有两种形态：
  - <repo>_<instance_id>.json     例: fastapi_11194.json
  - <repo>_<base_commit>.json     例: fastapi_016ab760...json

修法：对每个 commit 组，在「组内全部文件名」中找出唯一一个有内容的，覆盖其余空文件。

用法:
    python3 scripts/repair_links.py --manifest /tmp/allfiles.csv [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_manifest(path: Path) -> dict[str, int]:
    sizes: dict[str, int] = {}
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0] or row[0] == "name":
                continue
            try:
                sizes[row[0]] = int(row[1])
            except ValueError:
                continue
    return sizes


def group_names(instance_id: str, repo: str, commit: str, subdir: str, ext: str) -> list[str]:
    """一个 commit 组在这一层目录下的候选取名。"""
    short_repo = repo.split("/")[-1]
    return [
        f"{subdir}/{instance_id}{ext}",
        f"{subdir}/{short_repo}_{commit}{ext}",
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, help="文件清单 CSV，用于判定谁在 Kaggle 侧就是空的")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tasks", default=str(ROOT / "data" / "tasks.jsonl"))
    args = ap.parse_args()

    sizes = load_manifest(Path(args.manifest))
    tasks = [json.loads(l) for l in open(args.tasks)]

    # commit -> 该 commit 组涉及的任务
    by_commit: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in tasks:
        by_commit[(t["repo"], t["base_commit"])].append(t)

    totals = {"groups": 0, "repaired": 0, "already_ok": 0, "unresolved": 0}
    unresolved: list[str] = []

    for (repo, commit), group in sorted(by_commit.items()):
        for subdir, ext in (("graphs", ".json"), ("embeddings", ".npz")):
            names: list[str] = []
            for t in group:
                names += group_names(t["instance_id"], repo, commit, subdir, ext)
            # 去重并只保留清单里确实存在的
            names = [n for n in dict.fromkeys(names) if n in sizes]
            if not names:
                continue
            totals["groups"] += 1
            d = ROOT / "data" / subdir
            live = [n for n in names if (d / Path(n).name).exists() and (d / Path(n).name).stat().st_size > 0]
            if not live:
                totals["unresolved"] += 1
                unresolved.append(f"{subdir}: {repo}@{commit[:10]} -> {[Path(n).name for n in names]}")
                continue
            # 选体积最大的活文件作为源（同组内容相同，取最大最稳）
            src_name = max(live, key=lambda n: (d / Path(n).name).stat().st_size)
            src = d / Path(src_name).name
            for n in names:
                dst = d / Path(n).name
                if dst == src:
                    totals["already_ok"] += 1
                    continue
                if dst.exists() and dst.stat().st_size > 0:
                    totals["already_ok"] += 1
                    continue
                if args.dry_run:
                    print(f"  [dry] {dst.name}  <-  {src.name}  ({src.stat().st_size/1e6:.1f} MB)")
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                totals["repaired"] += 1

    print(json.dumps(totals, ensure_ascii=False, indent=2))
    if unresolved:
        print("未能修复的组（源文件本身也缺失）:")
        for u in unresolved:
            print("  " + u)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
