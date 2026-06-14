#!/usr/bin/env bash
# 每日 MinerU 续跑：把 fresh 待转文档在每日配额内逐步转完，并落桶 markdown + 去重 + 体检。
# 幂等——zip 缓存 + 内容寻址保证已转的不重复花配额；cache-miss 修复保证手册不被重转覆盖。
#
# 走正确摄入流程（kms product/qa update）：分类→设桶 env→batch（缓存 zip 免费 emit
# markdown，fresh 用配额）→后处理（语法修复+去重）。裸跑 mineru_batch_export 只产 zip
# 不落桶 markdown，已弃用。
#
# ⚠ MinerU 服务端节流：每日配额耗尽后，大批量提交（30/190 文件）会被排队、轮询长时间
# 不返回结果（实测 40 分钟 0 下载）；初始少量请求（1 文件）可成。故续跑用小批量 +
# 长等待让结果有时间回来：MINERU_BATCH_SIZE=5、--max-wait-min 20。下方 product/qa
# update 经 MINERU_BATCH_SIZE env 控制批大小（kms_cli 透传）。
set -u
cd "/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine" || exit 1
PY=.venv/bin/python
LOG="/tmp/mineru_daily_$(date +%Y%m%d_%H%M).log"

# 1. 还剩多少 fresh（用 cache-miss 修复后的判定）
REMAIN=$("$PY" - <<'EOF'
import sys,os; sys.path.insert(0,'.')
os.environ.pop('KMS_PRODUCT_FILES',None)
from main.mineru_batch_export import _list_input_files, _large_pdf_parts_all_cached
from main.mineru_source_index import SourceIndex
from main import knowledge_paths as kp
idx=SourceIndex.load(kp.KNOWLEDGE_ORGIN,kp.KNOWLEDGE_MINERU)
n=0
for p in _list_input_files(kp.KNOWLEDGE_ORGIN):
    try: h=idx.source_hash(p)
    except: n+=1; continue
    e=idx.lookup(h)
    if e and (kp.KNOWLEDGE_MINERU/e['zip']).exists(): continue
    if _large_pdf_parts_all_cached(p,kp.KNOWLEDGE_MINERU): continue
    n+=1
print(n)
EOF
)
echo "[$(date)] 剩余 fresh: $REMAIN" >> "$LOG"

# 2. fresh=0 → 全部转完, 自删 cron, 退出
if [ "$REMAIN" = "0" ]; then
  echo "[$(date)] 全部文档已转完, 续跑任务完成, 移除 crontab 自身。" >> "$LOG"
  (crontab -l 2>/dev/null | grep -v mineru_daily_drain.sh) | crontab - 2>/dev/null
  exit 42
fi

# 3. 正确流程：product update（每日页预算内）→ qa update
export MINERU_PAGE_BUDGET=1000
export MINERU_BATCH_SIZE=5
export PYTHONUNBUFFERED=1
"$PY" - >> "$LOG" 2>&1 <<'EOF'
import sys; sys.path.insert(0,'.')
from main.langchain_env import langchain_load_dotenv_if_present as L; L()
from main.ist_core.tui.kms_cli import run_kms_command
print("=== product update ==="); run_kms_command(["product","update"])
print("=== qa update ===");      run_kms_command(["qa","update"])
EOF
echo "[$(date)] 本日 product+qa update 结束" >> "$LOG"
