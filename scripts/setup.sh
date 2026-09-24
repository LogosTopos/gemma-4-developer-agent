#!/usr/bin/env bash
# 从 Kaggle 重建完整本地环境。需要已登录的 Kaggle CLI（`kaggle auth login`）。
#
#   ./scripts/setup.sh              # 全部：数据 + wheelhouse + venv
#   ./scripts/setup.sh --core       # 只下核心数据（约 900MB，跳过 20GB 快照）
#   ./scripts/setup.sh --venv       # 只建 Python 环境（需要 vendor/ 已存在）
set -euo pipefail

COMP="gemma-4-developer-agent"
WHEELHOUSE="metric/gemma-4-developer-agent-wheelhouse"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DO_CORE=0 DO_SNAP=0 DO_VENV=0
if [ $# -eq 0 ]; then DO_CORE=1; DO_SNAP=1; DO_VENV=1; fi
for arg in "$@"; do
  case "$arg" in
    --core) DO_CORE=1 ;;
    --snapshots) DO_SNAP=1 ;;
    --venv) DO_VENV=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg"; exit 2 ;;
  esac
done

command -v kaggle >/dev/null || { echo "❌ 未找到 kaggle CLI。安装：pip install kaggle"; exit 1; }
kaggle competitions list -s gemma >/dev/null 2>&1 || {
  echo "❌ Kaggle 未认证。先运行：kaggle auth login"; exit 1; }

mkdir -p data vendor logs

# ── 1. 生成文件清单（下载脚本依赖它区分 0 字节文件）──
if [ ! -f /tmp/allfiles.csv ]; then
  echo "==> 拉取竞赛文件清单…"
  TOKEN=""; : > /tmp/allfiles.csv
  for _ in $(seq 1 60); do
    if [ -z "$TOKEN" ]; then
      OUT=$(kaggle competitions files "$COMP" --csv 2>&1)
    else
      OUT=$(kaggle competitions files "$COMP" --csv --page-token "$TOKEN" 2>&1)
    fi
    TOKEN=$(echo "$OUT" | grep '^Next Page Token' | sed 's/Next Page Token = //' || true)
    echo "$OUT" | grep -v '^Next Page Token' | grep -v '^name,size' >> /tmp/allfiles.csv || true
    [ -z "$TOKEN" ] && break
  done
  echo "    $(wc -l < /tmp/allfiles.csv | tr -d ' ') 个文件"
fi

# ── 2. 核心数据：任务、代码图、嵌入、wheels、样例提交 ──
if [ "$DO_CORE" = 1 ]; then
  echo "==> 下载核心数据（约 900MB）…"
  python3 scripts/fetch.py --list /tmp/allfiles.csv \
    --pattern '^(graphs|embeddings|wheels|sample_submission|docker|sandbox)/'
  python3 scripts/fetch.py --list /tmp/allfiles.csv --pattern '^tasks\.jsonl$'
  python3 scripts/fetch.py --list /tmp/allfiles.csv --pattern '^HARNESS_README\.md$'

  echo "==> 修复 0 字节的 graph/embedding 文件（zip 丢失硬链接所致）…"
  python3 scripts/repair_links.py --manifest /tmp/allfiles.csv
fi

# ── 3. 仓库快照（20GB，评测必需）──
if [ "$DO_SNAP" = 1 ]; then
  echo "==> 下载 129 个仓库快照（约 20GB，耗时较长）…"
  python3 scripts/fetch.py --list /tmp/allfiles.csv --pattern '^snapshots/'
fi

# ── 4. wheelhouse：官方评测框架的 wheel ──
if [ ! -d vendor/wheelhouse ]; then
  echo "==> 下载官方 wheelhouse…"
  kaggle datasets download "$WHEELHOUSE" -p vendor/ -q
  mkdir -p vendor/wheelhouse
  unzip -o -q vendor/*.zip -d vendor/wheelhouse/
  echo "    $(ls vendor/wheelhouse | wc -l | tr -d ' ') 个 wheel"
fi

# ── 5. Python 环境（纯 Python 包，无需 GPU）──
if [ "$DO_VENV" = 1 ]; then
  echo "==> 创建 .venv 并安装…"
  PY="${PYTHON:-python3}"
  [ -d .venv ] || "$PY" -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q google-adk litellm networkx python-dotenv rich numpy pandas pytest docker pypdf
  .venv/bin/pip install -q --no-deps \
    vendor/wheelhouse/adk_eval_core-0.1.0-py3-none-any.whl \
    vendor/wheelhouse/adk_submission-0.2.11-py3-none-any.whl \
    vendor/wheelhouse/swegemma-0.2.7-py3-none-any.whl
  echo "==> 验证导入…"
  .venv/bin/python -c "import swegemma, adk_submission, adk_eval_core; print('   ✅ 框架导入正常')"
fi

echo
echo "✅ 完成。常用命令："
echo "    .venv/bin/python scripts/validate_submission.py submission/ --clean"
echo "    .venv/bin/python scripts/pack_submission.py submission/ -o dist/submission.zip"
