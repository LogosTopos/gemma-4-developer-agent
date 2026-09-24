#!/usr/bin/env python3
"""按竞赛文件清单下载，并把 Kaggle CLI 拉平的文件还原到原始目录结构。

用法:
    python3 scripts/fetch.py --list /tmp/allfiles.csv --pattern 'graphs/.*fastapi' 
    python3 scripts/fetch.py --list /tmp/allfiles.csv --paths-from files.txt
    python3 scripts/fetch.py --list /tmp/allfiles.csv --all

Kaggle CLI 的 `-p` 只是解包目录，会把 `a/b/c.txt` 落成 `c.txt`，
所以这里统一下到 _staging/，再按清单路径 move 回 data/。
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STAGING = ROOT / "_staging"
COMP = "gemma-4-developer-agent"


def load_manifest(path: Path) -> list[tuple[str, int]]:
    out = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0] or row[0] == "name":
                continue
            try:
                out.append((row[0], int(row[1])))
            except ValueError:
                continue
    return out


def download_one(remote: str, retries: int = 3) -> bool:
    """下载单个远程文件到 _staging/，成功后按原路径归档。"""
    target = DATA / remote
    if target.exists() and target.stat().st_size > 0:
        return True
    STAGING.mkdir(parents=True, exist_ok=True)
    flat = STAGING / Path(remote).name
    for attempt in range(1, retries + 1):
        if flat.exists():
            flat.unlink()
        proc = subprocess.run(
            ["kaggle", "competitions", "download", COMP, "-f", remote, "-p", str(STAGING), "-q"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and flat.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(flat), str(target))
            return True
        time.sleep(2 * attempt)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True, help="文件清单 CSV (name,size,creationDate)")
    ap.add_argument("--pattern", help="正则过滤文件路径")
    ap.add_argument("--paths-from", help="从文本文件读取确切路径（每行一个）")
    ap.add_argument("--all", action="store_true", help="下载清单中全部文件")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    entries = load_manifest(Path(args.list))
    if args.paths_from:
        wanted = {l.strip() for l in open(args.paths_from) if l.strip()}
        sel = [(n, s) for n, s in entries if n in wanted]
    elif args.pattern:
        rx = re.compile(args.pattern)
        sel = [(n, s) for n, s in entries if rx.search(n)]
    elif args.all:
        sel = entries
    else:
        ap.error("需要 --pattern / --paths-from / --all 之一")

    total_mb = sum(s for _, s in sel) / 1024 / 1024
    print(f"选中 {len(sel)} 个文件, 合计 {total_mb:.1f} MB")
    if args.dry_run:
        for n, s in sel[:50]:
            print(f"  {s/1024/1024:9.2f} MB  {n}")
        return 0

    done = skipped = failed = empty = 0
    for i, (name, size) in enumerate(sel, 1):
        target = DATA / name
        if target.exists():
            skipped += 1
            continue
        # 清单里 size==0 的文件在 Kaggle 侧就是空的（zip 丢失硬链接所致），下载必然 400
        if size == 0:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
            empty += 1
            continue
        ok = download_one(name)
        if ok:
            done += 1
        else:
            failed += 1
            print(f"  FAIL {name}", flush=True)
        if i % 25 == 0 or i == len(sel):
            print(f"  [{i}/{len(sel)}] ok={done} skip={skipped} empty={empty} fail={failed}", flush=True)

    print(f"完成: 下载 {done}, 已存在 {skipped}, 空文件占位 {empty}, 失败 {failed}")
    if empty:
        print("提示: 0 字节文件是已知数据问题，用 scripts/repair_links.py 从同 commit 副本修复")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
