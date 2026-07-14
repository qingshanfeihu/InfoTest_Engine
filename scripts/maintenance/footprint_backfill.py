"""阶段一：footprint 文法补全 —— 把 10.5 CLI 手册的命令语法灌进 footprint 知识树。

流程「切片 → extract_facts → route → merge → reconcile」，复用现有提取链，
零改 extractor/router/merger/schema/reconcile（PLAN_footprint_v2_compile.md §五-阶段一）。

切片器（纯代码、确定性）：以命令签名行为锚，一片 = 签名行 + 说明段 + <table> 参数表
+ 注意段，到下一签名行/`##` 标题止；no/show/clear 各自成片；多片打包到 ≤MAX_SLICE_CHARS
的批次喂一次 LLM（带最近 `##` 章节标题作上下文）。

merge evidence 门（merger._evidence_supports）保证不编造：evidence_quote 须在手册原文
≥60% 连续命中，LLM 编的自动丢。

用法：
    .venv/bin/python -m scripts.maintenance.footprint_backfill            # 全量手册
    .venv/bin/python -m scripts.maintenance.footprint_backfill --dry-run  # 只切片统计不调 LLM
    .venv/bin/python -m scripts.maintenance.footprint_backfill --limit 5  # 只跑前 5 批（调试）
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("footprint_backfill")

# 单批喂 LLM 的字符上限（含章节上下文）。批越密、命令越多 → LLM 输出越易逼近 max_tokens
# 截断（实测 6000→单批最多 43 命令、completion ~7.9K 逼近 8192）。2500 ≈ 单批 ~15 命令、
# completion ~3K，留足余量。（单遍漏命令的真根因是端点把 facts 数组 stringify，已靠
# extractor.EXTRACTION_TOOL 的 strict:true 治本，此处只防 max_tokens 截断。）
MAX_SLICE_CHARS = 2500
MAX_WORKERS = 6                  # 并发 LLM 调用数（function_llm 自带 cache + retry）

_CJK_RE = re.compile(r"[一-鿿]")
# 命令签名行：行首命令 token（可带 no/show/clear 前缀），且含 <param>/[param]/{a|b} 记法
_NOTATION_RE = re.compile(r"[<\[{][a-zA-Z_]")
_HEADER_RE = re.compile(r"^#{1,4}\s+\S")
_CMD_HEAD_RE = re.compile(r"^(no |show |clear )?[a-z][a-z0-9_]*( |$)")
# 无参也合法的命令签名：操作动词打头 + 纯小写词（如 "show sdns listener"、"config memory"、
# "write file"）。show/clear/no 是查询/清除动词；write/config 是存盘/恢复动词——同样是无参命令，
# 漏了它们会让整段 write/config(配置保存与恢复)命令永远进不了 footprint(config.memory 缺失根因)。
_QUERY_CMD_RE = re.compile(r"^(show|clear|no|write|config) [a-z][a-z0-9_ ]*$")


def _is_signature(line: str, *, bold_only: bool = False) -> bool:
    """是否命令签名锚行。

    ``bold_only``：文档用 markdown 粗体约定标命令主体时（新手册），只认粗体行为命令定义。

    锚行两类（确定性，不含语义字典）：
    1. 命令头 + 含 <param>/[param]/{a|b} 记法（如 ``sdns listener <ip> [port]``）；
    2. 纯 show/clear/no 查询命令、无参数（如 ``show sdns listener``）。
    含 CJK 的行（说明文 / 参数表）一律不是签名。具体取值的示例行
    （``sdns listener 172.16.34.70``）无记法、非查询 → 不作锚（仍留在片体里给 LLM 看）。
    """
    s = line.strip()
    had_bold = "**" in s
    # 剥 markdown 粗体标记 `**`/`__`：手册命令行是 `**命令主体** _斜体参数_` 格式（表1-1），
    # 行首的 `**` 会让 _CMD_HEAD_RE（要求行首小写命令 token）匹配失败。检测按纯文本判，
    # 片体仍保留原 markdown 供 LLM 用粗体/斜体约定区分命令与参数。
    s = s.replace("**", "").replace("__", "").strip()
    if not s or _CJK_RE.search(s):
        return False
    # 新手册（bold_doc，表1-1 用粗体标命令主体）：**粗体本身就是"这是命令"的确定性标记**——
    # 凡「粗体 + 命令头 token」的非中文行即命令签名，不再额外要求记法或查询动词。否则一整类
    # 命令在切片层就漏掉、LLM 永远看不到（strict 等下游修复够不着）：
    #   ① 无参命令 disable/exit/quit/help/?/ha ssi on/off（首词非 show/clear/no/write/config）；
    #   ② 记法前有空格或非字母开头的参数 `< host_name>`/`<1-4094>`（_NOTATION_RE 紧跟字母会挂）。
    if bold_only:
        return had_bold and bool(_CMD_HEAD_RE.match(s))
    # 旧 MinerU（无粗体约定）：用记法/查询动词启发式，避免把示例/输出误切成命令。
    if not _CMD_HEAD_RE.match(s):
        return False
    if _NOTATION_RE.search(s):
        return True
    return bool(_QUERY_CMD_RE.match(s))


@dataclass
class Chunk:
    """一条命令片：签名行 + 紧随的说明/参数表/注意段，附最近 `##` 章节标题。"""

    section: str          # 最近的 `##` 章节标题（上下文）
    body: str             # 签名行 + 后续直到下一签名/标题的文本
    source_file: str      # 手册相对路径（evidence_file）

    def char_len(self) -> int:
        return len(self.section) + len(self.body)


def slice_manual(md_path: Path, rel_path: str) -> list[Chunk]:
    """把一份手册切成命令片列表。

    遍历行：维护「最近章节标题」；遇签名锚行起一个新片，吸收后续非签名/非标题行，
    到下一签名行或下一 `##` 标题止。无签名锚的纯叙述章节被跳过（不产片）。
    """
    lines = md_path.read_text(encoding="utf-8").split("\n")
    # 自动检测：文档是否用 markdown 粗体约定标命令主体（新手册格式，表1-1）。
    # 是则只认粗体行为命令定义（剔除示例/输出等非粗体噪声行）；否则用纯文本启发式（MinerU 兼容）。
    # 阈值取 3：小章节（Chapter7/16 各 ~6 命令）也要识别为 bold_doc，否则走旧启发式漏掉无参命令；
    # 引言/附录（0-2 粗体、本无命令）仍判 False，不受影响。
    bold_doc = sum(1 for ln in lines if ln.lstrip().startswith("**")) >= 3
    chunks: list[Chunk] = []
    section = ""
    cur: list[str] | None = None

    def flush() -> None:
        nonlocal cur
        if cur:
            body = "\n".join(cur).strip()
            if body:
                chunks.append(Chunk(section=section, body=body, source_file=rel_path))
        cur = None

    for ln in lines:
        if _HEADER_RE.match(ln):
            flush()
            section = ln.strip()
            continue
        if _is_signature(ln, bold_only=bold_doc):
            flush()
            cur = [ln]
            continue
        if cur is not None:
            cur.append(ln)
    flush()
    return chunks


def pack_batches(chunks: list[Chunk]) -> list[list[Chunk]]:
    """把**同 source_file** 的相邻片打包到 ≤MAX_SLICE_CHARS 的批次。

    同批共享章节上下文拼接；单片超限自成一批（不切碎命令）。**强制单源**：source_file
    变化即断批——render_batch 用 batch[0].source_file 作头/evidence_file 锚，混源批会让 LLM
    把 A 章命令的 evidence_file 填成 B 章 → 证据门查错文件误丢。run_backfill 本就 per-chapter
    调用此函数，这里再硬保证一次，杜绝调用方传混源 chunks 时静默错配。
    """
    batches: list[list[Chunk]] = []
    cur: list[Chunk] = []
    cur_len = 0
    for ch in chunks:
        clen = ch.char_len()
        if cur and (cur_len + clen > MAX_SLICE_CHARS or cur[-1].source_file != ch.source_file):
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append(ch)
        cur_len += clen
    if cur:
        batches.append(cur)
    return batches


def render_batch(batch: list[Chunk]) -> str:
    """把一批片渲染成喂 LLM 的文本：按章节分组，标注 evidence_file。"""
    parts: list[str] = []
    last_section = None
    src = batch[0].source_file if batch else ""
    parts.append(f"以下是产品 CLI 手册 `{src}` 的命令定义片段。\n")
    for ch in batch:
        if ch.section and ch.section != last_section:
            parts.append(f"\n{ch.section}")
            last_section = ch.section
        parts.append(ch.body)
    return "\n".join(parts)


# 适配后缀：extractor 的 system prompt 原写"读 agent 工作记忆"，字段规则对手册同样适用，
# 加一句适配、不重写（PLAN §五-2）。
_MANUAL_ADAPT_SUFFIX = """

## 本次输入是产品 CLI / APP 手册段落（非对话工作记忆）

上面提供的 evidence_file 路径就是来源手册，evidence_file 字段直接填它。

### 手册命令行符号约定（表1-1，据此解析命令与参数）
- **粗体** = 命令行主体（命令本身）；*斜体* = 命令参数。**feature_path 只取命令主体（粗体）的 token**，
  斜体参数一律不进 feature_path。
- `<param>` 必选参数；`[param]` 可选参数；`{ x | y | … }` 从多个选项选一或多个；
  `[ x | y | … ]` 从多个选项选一或不选。这些记法只进 cli_syntax，不进 feature_path。
- `no` / `show` / `clear` 是操作子命令前缀，feature_path 要剥掉（配置/no/show/clear 各提一条 cli_command）。
- 参数取值（具体值、正则表达式）是参数的取值，不是命令 token，绝不写进命令主体。

### 提取要点
- 逐条命令提取 cli_command：cli_syntax = 粗体命令主体 + 斜体参数（按原文记法还原完整签名）；
  parameters 从紧随的参数表逐行提取（name/required/default/value_range/type/desc 按原文给）。
- "注意" / "说明"段里的"条件 → 结论/默认值/限制"提取为 decision_rule。
- evidence_quote 必须是手册原文片段（命令签名行 / 规则句），未经改写。
"""


def build_backfill_llm():
    """构建手册提取用 LLM 调用 (system, user) -> dict；无 key 返回 None。

    复用 function_llm.chat_completion（json_object + retry + truncation + cache），
    haiku tier 模型降成本。system prompt = extractor 原契约 + 手册适配后缀。
    """
    from main.langchain_env import langchain_load_dotenv_if_present
    langchain_load_dotenv_if_present()

    from main.ist_core.agents._llm import (
        ist_core_tier_model,
        resolve_llm_api_key,
        resolve_llm_base_url,
    )

    api_key = resolve_llm_api_key()
    if not api_key:
        logger.error("无 OPENAI_API_KEY，无法调 LLM")
        return None

    import requests
    from main.function_llm import TruncationError, chat_completion

    base_url = resolve_llm_base_url()
    model = ist_core_tier_model("haiku")
    session = requests.Session()
    logger.info("backfill LLM: model=%s base_url=%s", model, base_url)

    def _call(system_prompt: str, user_prompt: str, tool: dict | None = None):
        try:
            return chat_completion(
                session, api_key,
                system_prompt + _MANUAL_ADAPT_SUFFIX, user_prompt,
                # 16384：mimo 1M 上下文，输出上限远不止 8192。strict schema 要求填全字段(含 null)
                # 输出更冗长(实测密集批 completion 逼近 7K)，放大保底避免 max_tokens 截断丢整批。
                model=model, base_url=base_url,
                max_tokens=16384, temperature=0.1, top_p=0.1,
                tool=tool,
            )
        except TruncationError:
            logger.warning("LLM 输出截断，跳过该批")
            return {"facts": []}

    return _call


@dataclass
class RunStats:
    batches: int = 0
    facts_extracted: int = 0
    merged_create: int = 0
    merged_append: int = 0
    merged_update: int = 0
    skipped: int = 0
    by_skip_detail: dict = field(default_factory=dict)


def run_backfill(*, dry_run: bool = False, limit: int = 0,
                 manuals: list[Path] | None = None,
                 existing_facts: dict | None = None,
                 footprint_dir: Path | None = None,
                 nodes_subdir: str = "nodes") -> RunStats:
    from main import knowledge_paths as kp
    from main.ist_core.memory.footprint import (
        extract_facts, route_facts, merge_fact, reconcile,
    )
    from main.ist_core.memory.dream import _load_existing_facts

    root = Path(__file__).resolve().parents[2]
    if manuals is None:
        # 默认10.5 CLI 手册（章节制，粗体命令约定，表1-1）。
        manuals = sorted(
            (root / "knowledge/data/markdown/product/product").glob("cli_10.5_*.md")
        )

    if footprint_dir is None:
        footprint_dir = kp.KNOWLEDGE_FOOTPRINTS
    nodes_dir = footprint_dir / nodes_subdir
    nodes_dir.mkdir(parents=True, exist_ok=True)

    # 切片 + 打包
    all_batches: list[list[Chunk]] = []
    print(f"[DEBUG-RB] manuals count={len(manuals)}, root={root}", flush=True)
    for md in manuals:
        rel = md.relative_to(root).as_posix()
        chunks = slice_manual(md, rel)
        print(f"[DEBUG] {md.name}: {len(chunks)} chunks", flush=True)
        batches = pack_batches(chunks)
        logger.info("%s: %d 片 → %d 批", md.name, len(chunks), len(batches))
        all_batches.extend(batches)

    if limit > 0:
        all_batches = all_batches[:limit]
    logger.info("总计 %d 批待处理", len(all_batches))

    stats = RunStats(batches=len(all_batches))
    if dry_run:
        sig_total = sum(len(b) for b in all_batches)
        logger.info("[dry-run] %d 批 / %d 命令片，不调 LLM", len(all_batches), sig_total)
        return stats

    llm_chat = build_backfill_llm()
    if llm_chat is None:
        return stats

    # existing_facts 快照（启动时取一次；供 LLM 复用 fact_key，避免每批重载 O(n²)）。
    # 传入 existing_facts 可覆盖（如范围化重生成时只传相关子树，避免把全树塞进 prompt）。
    # 注意：传 nodes_dir 而非 footprint_dir，避免扫描到其他版本的节点。
    existing = existing_facts if existing_facts is not None else _load_existing_facts(nodes_dir)

    # 并发提取
    def _extract(batch: list[Chunk]):
        text = render_batch(batch)
        return extract_facts(text, llm_chat=llm_chat, existing_facts=existing)

    all_facts = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(_extract, b): i for i, b in enumerate(all_batches)}
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                facts = fut.result()
            except Exception as exc:
                logger.warning("批 %d 提取失败: %s", futs[fut], exc)
                continue
            all_facts.extend(facts)
            if done % 20 == 0 or done == len(futs):
                logger.info("提取进度 %d/%d，累计 %d facts", done, len(futs), len(all_facts))

    stats.facts_extracted = len(all_facts)

    # 串行 route + merge（写盘，避免并发竞态）
    for rf in route_facts(all_facts, footprint_dir, nodes_subdir=nodes_subdir):
        r = merge_fact(rf, footprint_dir)
        if r.action == "create":
            stats.merged_create += 1
        elif r.action == "append":
            stats.merged_append += 1
        elif r.action == "update":
            stats.merged_update += 1
        else:
            stats.skipped += 1
            stats.by_skip_detail[r.detail] = stats.by_skip_detail.get(r.detail, 0) + 1

    # 全树 reconcile
    rec = reconcile(footprint_dir, nodes_subdir=nodes_subdir)
    logger.info("reconcile: %s", rec)
    return stats


def _backup_and_clear_nodes(footprint_dir: Path | None = None,
                            nodes_subdir: str = "nodes") -> Path | None:
    """rebuild 前：把现有 nodes/*.json 备份到 .intermediate 带时间戳目录后清空。

    返回备份目录（无节点可备份时返回 None）。清空保证全量重建从干净状态起，
    existing_facts 为空 → fact_key 全新生成，不与旧数据交叉污染。
    """
    import shutil
    from datetime import datetime
    from main import knowledge_paths as kp

    if footprint_dir is None:
        footprint_dir = kp.KNOWLEDGE_FOOTPRINTS
    nodes = footprint_dir / nodes_subdir
    files = sorted(nodes.glob("*.json")) if nodes.exists() else []
    if not files:
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_name = f"footprint_nodes_backup_{nodes_subdir}_{ts}" if nodes_subdir != "nodes" else f"footprint_nodes_backup/{ts}"
    bak = kp.KNOWLEDGE_INTERMEDIATE / bak_name
    bak.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, bak / f.name)
        f.unlink()
    logger.info("rebuild: 已备份 %d 节点 → %s 并清空 %s/", len(files), bak, nodes_subdir)
    return bak


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="footprint 文法补全（手册 → footprint 树）")
    parser.add_argument("--dry-run", action="store_true", help="只切片统计，不调 LLM")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 批（调试）")
    parser.add_argument(
        "--rebuild", action="store_true",
        help="全量重建：先备份现有 nodes 到 .intermediate/ 再清空，"
             "然后从空树重抽（默认是增量补全，复用 existing 仅追加新事实）",
    )
    parser.add_argument(
        "--nodes-subdir", type=str, default="nodes",
        help="footprint nodes 子目录名（相对于 knowledge/footprints/）。默认 nodes；"
             "版本隔离示例：--nodes-subdir nodes_10.4.6r2",
    )
    parser.add_argument(
        "--manuals", type=str, default="",
        help="手册文件 glob 模式（相对项目根）。默认 cli_10.5_*.md；"
             '示例："knowledge/data/markdown/product/10_4_6_R2/product/cli_10.4.6_*.md"',
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from main import knowledge_paths as kp

    nodes_subdir = args.nodes_subdir

    manuals_list: list[Path] | None = None
    if args.manuals:
        root = Path(__file__).resolve().parents[2]
        import glob as _glob
        manuals_list = sorted(Path(p) for p in _glob.glob(str(root / args.manuals)))
        print(f"[DBG2] root={root} file={Path(__file__).resolve()} manuals_in={args.manuals} glob_pat={str(root / args.manuals)} found={len(manuals_list)}", flush=True)

    if args.rebuild and not args.dry_run:
        bak = _backup_and_clear_nodes(nodes_subdir=nodes_subdir)
        print(f"[rebuild] 已备份旧节点到 {bak} 并清空 {nodes_subdir}/" if bak
              else f"[rebuild] {nodes_subdir}/ 已空，直接全量生成")

    stats = run_backfill(
        dry_run=args.dry_run, limit=args.limit,
        manuals=manuals_list, nodes_subdir=nodes_subdir,
    )
    print("\n=== footprint backfill 统计 ===")
    print(f"批次:        {stats.batches}")
    if not args.dry_run:
        print(f"提取 facts:  {stats.facts_extracted}")
        print(f"merge create:{stats.merged_create}")
        print(f"merge append:{stats.merged_append}")
        print(f"merge update:{stats.merged_update}")
        print(f"skipped:     {stats.skipped}  {stats.by_skip_detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
