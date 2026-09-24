#!/usr/bin/env python3
"""打包提交：先校验，再打包，最后解压复检。

用法:
    python3 scripts/pack_submission.py submission/ -o dist/submission.tar.gz
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("submission_dir")
    ap.add_argument("-o", "--output", default=str(ROOT / "dist" / "submission.tar.gz"))
    ap.add_argument("--skip-validate", action="store_true")
    args = ap.parse_args()

    sub = Path(args.submission_dir).resolve()
    out = Path(args.output).resolve()

    # 1) 校验
    if not args.skip_validate:
        rc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_submission.py"),
             str(sub), "--clean"],
            cwd=ROOT,
        ).returncode
        if rc != 0:
            print("❌ 校验未通过，拒绝打包")
            return rc

    # 2) 清垃圾
    for name in JUNK:
        for p in sub.rglob(name):
            p.unlink()

    # 3) 打包（内容位于归档根部，不含顶层目录）
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    members = sorted(p for p in sub.rglob("*") if p.is_file())
    with tarfile.open(out, "w:gz") as tf:
        for p in members:
            if p.is_symlink():
                print(f"❌ 符号链接不能打包: {p}")
                return 1
            tf.add(p, arcname=str(p.relative_to(sub)))

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"📦 已打包 {len(members)} 个文件 → {out} ({size_mb:.2f} MiB)")
    for p in members:
        print(f"   {p.relative_to(sub)}")

    # 4) 解压复检：确保归档里的结构仍能通过校验
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(out) as tf:
            tf.extractall(td, filter="data")
        rc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_submission.py"), td],
            cwd=ROOT, capture_output=True, text=True,
        )
        if rc.returncode != 0:
            print("❌ 解压复检未通过：")
            print(rc.stdout[-2000:])
            return rc.returncode
        print("✅ 解压复检通过（归档结构可用）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
