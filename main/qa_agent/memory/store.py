"""MemoryStore facade：封装 backend 调用 + 三闸路径校验 + frontmatter 解析。

参考实现：
- main/qa_agent/tools/deepagent/file_tools._resolve_inside_root（三闸 traversal/blacklist/whitelist）
- main/qa_agent/middleware/per_turn_skill_reminder._FRONTMATTER_RE（yaml-free 解析）
- deepagents.backends.protocol.BackendProtocol（read/write/edit/glob/ls 协议）

为什么是 facade：
1. middleware / dream / fork agent 都需要语义化方法（read_agents_md / read_long_term），
   而不是裸调 backend.read("/memories/preferences.md")。
2. 三闸校验集中在这里，所有写入入口共用，避免重复实现。
3. AGENTS.md 走真实磁盘（git 跟踪），其他记忆走 backend；facade 统一接口。
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deepagents.backends.protocol import BackendProtocol  # noqa: F401

logger = logging.getLogger(__name__)


# 仿 per_turn_skill_reminder._FRONTMATTER_RE
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 闸 3：basename 字符白名单（与 deepagents store namespace 字符一致 + 文件扩展名场景）
_BASENAME_RE = re.compile(r"^[A-Za-z0-9_\-.]+$")

# 闸 2：合法子目录前缀（写入路径必须命中其一）
_ALLOWED_WRITE_PREFIXES = (
    "/memories/preferences",
    "/memories/review_conclusions/",
    "/memories/feedback/",
    "/memories/reviews/",
    "/memories/reference/",
    "/working/",
)

# 顶层 AGENTS.md 单独允许（dream task 写入）
_ALLOWED_TOP_LEVEL_WRITE = {"/memories/AGENTS.md"}


class MemoryStore:
    """记忆子系统的统一门面。

    构造时持有：
    - backend：CompositeBackend，主 agent / fork agent / dream task 共享
    - root_disk：真实磁盘根（memory/），用于 AGENTS.md 与 .dream 锁
    """

    def __init__(self, backend: BackendProtocol, root_disk: Path) -> None:
        self._backend = backend
        self._root = root_disk.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 三闸路径校验
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_virtual_path(rel: str, *, for_write: bool) -> str:
        """三闸校验。

        闸 1：拒 ".."、绝对外部路径、~。
        闸 2：必须以 /working/ 或 /memories/ 开头；写入时必须命中 _ALLOWED_WRITE_PREFIXES
              或 _ALLOWED_TOP_LEVEL_WRITE。
        闸 3：每段 basename 必须匹配 [A-Za-z0-9_\\-.]+。
        """
        text = (rel or "").strip()
        if not text:
            raise PermissionError("memory path is empty")
        if text.startswith("~") or "~" in text.split("/"):
            raise PermissionError(f"memory path may not contain ~: {rel!r}")
        if not text.startswith("/"):
            raise PermissionError(f"memory path must be absolute (start with /): {rel!r}")

        parts = text.split("/")
        if ".." in parts:
            raise PermissionError(f"memory path traversal not allowed: {rel!r}")

        for seg in parts:
            if seg == "":
                continue
            if not _BASENAME_RE.match(seg):
                raise PermissionError(
                    f"memory path segment {seg!r} contains disallowed characters"
                )

        if not (text.startswith("/working/") or text.startswith("/memories/")):
            raise PermissionError(
                f"memory path must live under /working/ or /memories/: {rel!r}"
            )

        if for_write:
            if text in _ALLOWED_TOP_LEVEL_WRITE:
                return text
            if not any(text.startswith(p) for p in _ALLOWED_WRITE_PREFIXES):
                raise PermissionError(
                    f"memory write path not in allowlist: {rel!r}"
                )
        return text

    # ------------------------------------------------------------------
    # frontmatter
    # ------------------------------------------------------------------

    @staticmethod
    def parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
        """从 markdown 头解析 frontmatter（仿 SKILL.md 风格，yaml-free）。

        返回 (字段 dict, 正文)。无 frontmatter 时返回 ({}, content)。
        识别字段：name / description / keywords / created / updated / turn_count。
        """
        m = _FRONTMATTER_RE.match(content)
        if not m:
            return {}, content
        fm_text = m.group(1)
        body = content[m.end():]

        fields: dict[str, str] = {}
        cur_key: str | None = None
        for raw_line in fm_text.splitlines():
            if ":" in raw_line and not raw_line.startswith((" ", "\t")):
                key, _, val = raw_line.partition(":")
                cur_key = key.strip()
                fields[cur_key] = val.strip()
            elif cur_key and raw_line.strip():
                fields[cur_key] = (fields.get(cur_key, "") + " " + raw_line.strip()).strip()
        return fields, body

    @staticmethod
    def render_frontmatter(fields: dict[str, str]) -> str:
        lines = ["---"]
        for k, v in fields.items():
            lines.append(f"{k}: {v}")
        lines.append("---")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    # ------------------------------------------------------------------
    # AGENTS.md（真实磁盘 + git 跟踪）
    # ------------------------------------------------------------------

    def agents_md_disk_path(self) -> Path:
        return self._root / "AGENTS.md"

    def read_agents_md(self, *, max_lines: int = 300) -> str:
        """读 memory/AGENTS.md（真实磁盘），返回前 max_lines 行。

        注：MemoryMiddleware 通过 backend.download_files(["/memories/AGENTS.md"])
        从虚拟 fs 读，那里走 StoreBackend 取的是上一次 dream 写入的副本。
        本方法专用于 dream task / 注入中间件直接读磁盘最新版（git 跟踪权威源）。
        """
        path = self.agents_md_disk_path()
        try:
            if not path.exists():
                return ""
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("read AGENTS.md 失败: %s", exc)
            return ""
        lines = text.splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [f"... [truncated to {max_lines} lines]"]
        return "\n".join(lines)

    def update_agents_md(self, content: str) -> None:
        """覆盖写 memory/AGENTS.md。仅 dream task 使用。原子写入。"""
        path = self.agents_md_disk_path()
        tmp = path.with_suffix(path.suffix + f".tmp.{int(time.time() * 1000)}")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            logger.warning("update AGENTS.md 失败: %s", exc)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def sync_agents_md_to_backend(self) -> None:
        """把磁盘 AGENTS.md 同步到 backend（StoreBackend），让 MemoryMiddleware 能读到。

        deepagents MemoryMiddleware 通过 backend.download_files 加载，所以必须先
        把磁盘内容塞进 backend。每次启动 + dream 写完后调用。

        实现要点（吸取 deepagents 0.5.9 的 edit() 行为教训）：
        - 不能用 edit(old_string="", ..., replace_all=True)：deepagents 的
          perform_string_replacement 在 old_string 为空时会算出 len(content)+1 个
          匹配点，replace_all 会在每个字符间插入 new_string，导致字节量指数爆炸
          （iter 5 332MB → iter 6 3.3GB 实测）
        - 正确做法：先 read 拿到当前内容，用它作为 old_string 调 edit，整段替换；
          首次写入则直接 write
        """
        text = self.read_agents_md(max_lines=10_000)
        if not text:
            return
        try:
            rr = self._backend.read("/memories/AGENTS.md", offset=0, limit=10_000)
            if rr.error is None and rr.file_data is not None:
                existing = self._file_data_to_str(rr.file_data)
                if existing == text:
                    return  # 已是最新，跳过
                if existing:
                    res = self._backend.edit(
                        "/memories/AGENTS.md", existing, text, replace_all=False
                    )
                    if not res.error:
                        return
            # 文件不存在或 edit 失败 → write
            self._backend.write("/memories/AGENTS.md", text)
        except Exception as exc:
            logger.warning("sync AGENTS.md to backend 失败: %s", exc)

    # ------------------------------------------------------------------
    # L2 长期记忆（真实磁盘 memory/long_term/，与 Claude Code 对齐）
    # ------------------------------------------------------------------
    #
    # 设计变更（2026-05-21）：原 plan 把 long-term 路由到 deepagents StoreBackend
    # （路径 /memories/）。实测发现走 backend.glob/read 在非 langgraph 上下文
    # （TUI slash 命令、dream cron）需要显式 store= 注入，且 InMemoryStore 跨进程
    # 不持久。统一改用真实磁盘 memory/long_term/，方案与 Claude Code 一致：
    # - long_term/preferences.md
    # - long_term/feedback/<topic>.md
    # - long_term/review_conclusions/<bug-id>.md
    #
    # 路径白名单仍由 _resolve_virtual_path 校验（兼容旧 /memories/ 前缀的输入，
    # 自动 normalize 到 long_term/）。

    @staticmethod
    def _normalize_to_long_term(rel: str) -> str:
        """把 /memories/foo.md / memories/foo.md 归一化成 long_term/foo.md。

        历史遗留路径（Claude Code 用 /memories/）保留兼容；新代码统一 long_term/。
        """
        text = (rel or "").strip()
        if not text:
            return ""
        # 去掉前导 /
        text = text.lstrip("/")
        # /memories/ → long_term/
        if text.startswith("memories/"):
            text = "long_term/" + text[len("memories/"):]
        elif not text.startswith("long_term/"):
            # rel_path 是 long_term/preferences.md 的简写（preferences.md / feedback/x.md）
            if text in ("preferences.md",) or text.startswith(("feedback/", "review_conclusions/")):
                text = "long_term/" + text
        return text

    def _long_term_disk_path(self, rel_path: str) -> Path:
        """返回真实磁盘上的 long_term/* 路径，过三闸校验。"""
        normalized = self._normalize_to_long_term(rel_path)
        # 三闸校验：用 /memories/ 前缀校验（白名单认这个）
        check_path = "/memories/" + normalized[len("long_term/"):] if normalized.startswith("long_term/") else "/memories/" + normalized
        self._resolve_virtual_path(check_path, for_write=True)
        return self._root / normalized

    def read_long_term_by_path(self, rel_path: str) -> str:
        """按精确路径读取 long_term/ 下的文件内容。

        通用方法——key_resolvers 回调用此直接读指定文件。
        返回文件内容字符串，不存在时返回空字符串。
        """
        try:
            normalized = self._normalize_to_long_term(rel_path)
            path = self._root / normalized
            if not path.exists():
                return ""
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.debug("read_long_term_by_path %s 失败: %s", rel_path, exc)
            return ""

    def read_long_term(
        self, query: str, *, top_k: int = 3
    ) -> list[tuple[str, str]]:
        """检索 long_term/ 下与 query 关键词重合度高的文件。

        返回 [(path_in_memory_root, content), ...]，最多 top_k 条。
        总数 < 10 时全返回（跳过打分）。
        """
        long_dir = self._root / "long_term"
        if not long_dir.exists():
            return []

        candidates: list[Path] = []
        try:
            for f in long_dir.rglob("*.md"):
                if f.is_file():
                    candidates.append(f)
        except Exception as exc:
            logger.debug("read_long_term scan 失败: %s", exc)
            return []
        if not candidates:
            return []

        if len(candidates) <= 10:
            selected = candidates
        else:
            selected = self._top_k_by_keyword_disk(candidates, query, top_k=top_k)

        out: list[tuple[str, str]] = []
        for f in selected:
            try:
                content = f.read_text(encoding="utf-8")
            except Exception as exc:
                logger.debug("read_long_term read %s 失败: %s", f, exc)
                continue
            try:
                rel = f.relative_to(self._root).as_posix()
            except ValueError:
                rel = str(f)
            out.append((rel, content))
        return out

    def _top_k_by_keyword_disk(
        self, candidates: list[Path], query: str, *, top_k: int
    ) -> list[Path]:
        """磁盘版按 query 切词与 frontmatter.keywords 求交集打分。"""
        terms = {t for t in re.split(r"[^\w一-鿿]+", (query or "").lower()) if t}
        if not terms:
            return candidates[:top_k]
        scored: list[tuple[int, Path]] = []
        for f in candidates:
            try:
                # 只读首 4KB 做打分用
                with f.open("rb") as fh:
                    head = fh.read(4096).decode("utf-8", errors="replace")
            except Exception:
                scored.append((0, f))
                continue
            fields, _ = self.parse_frontmatter(head)
            keywords = (fields.get("keywords", "") or "").lower()
            kw_set = {k.strip() for k in re.split(r"[,\s]+", keywords) if k.strip()}
            hits = len(terms & kw_set)
            body_hits = sum(1 for t in terms if t and t in head.lower())
            scored.append((hits * 10 + body_hits, f))
        scored.sort(key=lambda x: (-x[0], x[1].as_posix()))
        return [p for _, p in scored[:top_k]]

    def read_footprints(
        self, query: str, *, top_k: int = 2
    ) -> list[tuple[str, str]]:
        """检索 footprint 知识库，返回与 query 最相关的 footprint 摘要。

        走 FootprintIndex 单例（懒加载 + 多路匹配）。
        返回 [(feature_id, formatted_summary), ...]。
        """
        try:
            from main.qa_agent.memory.footprint import get_footprint_index
            return get_footprint_index().search(query, top_k=top_k)
        except Exception as exc:
            logger.debug("read_footprints 失败: %s", exc)
            return []

    def lookup_footprint(self, command: str) -> dict | None:
        """精确查找 footprint（供 qa_footprint_lookup tool 调用）。

        - 完整命令: "http rewrite body" → leaf 完整内容
        - 前缀命令: "slb mode" → 子节点列表
        - 未命中: None
        """
        try:
            from main.qa_agent.memory.footprint import get_footprint_index
            return get_footprint_index().lookup(command)
        except Exception as exc:
            logger.debug("lookup_footprint 失败: %s", exc)
            return None

    @staticmethod
    def _format_footprint(data: dict) -> str:
        """将 footprint JSON 格式化为注入用的简洁摘要。"""
        lines: list[str] = []
        fid = data.get("feature_id", "?")
        level = data.get("level", "?")
        meta = data.get("footprint_meta", {})
        lines.append(f"[{fid}] ({level}, verified {meta.get('verified_count', 0)}x)")

        cli = data.get("cli", {}).get("commands", [])
        for cmd in cli[:5]:
            lines.append(f"  cmd: {cmd.get('command', '')}")

        for r in data.get("decision_rules", [])[:4]:
            cond = r.get("condition", "")[:100]
            dec = r.get("decision", "")
            if dec:
                lines.append(f"  rule: {cond} → {dec}")
            else:
                lines.append(f"  rule: {cond}")

        for b in data.get("behaviors", [])[:3]:
            lines.append(f"  behavior: {b.get('content', '')[:100]}")

        for iss in data.get("known_issues", [])[:4]:
            lines.append(f"  issue: {iss.get('issue_id', '')} {iss.get('title', '')[:60]}")

        vs = data.get("version_scope", {})
        if vs.get("product_versions"):
            lines.append(f"  versions: {', '.join(vs['product_versions'][:5])}")

        return "\n".join(lines)

    def upsert_long_term(
        self,
        rel_path: str,
        content: str,
        *,
        mode: str = "append",
        keywords: str | None = None,
    ) -> None:
        """写入 long_term/ 下文件。mode: append | replace。

        - 自动维护 frontmatter（created/updated/keywords/turn_count）
        - 三闸校验 + 路径归一化
        - 原子写入（tmp + replace）
        """
        try:
            path = self._long_term_disk_path(rel_path)
        except Exception as exc:
            logger.warning("upsert_long_term path resolve 失败 %s: %s", rel_path, exc)
            return

        existing = ""
        if path.exists():
            try:
                existing = path.read_text(encoding="utf-8")
            except Exception:
                existing = ""

        fields, body = self.parse_frontmatter(existing) if existing else ({}, "")
        now = self._now_iso()
        if not fields.get("created"):
            fields["created"] = now
        fields["updated"] = now
        if keywords:
            fields["keywords"] = keywords
        try:
            fields["turn_count"] = str(int(fields.get("turn_count", "0") or "0") + 1)
        except Exception:
            fields["turn_count"] = "1"

        if mode == "replace":
            new_body = content
        else:
            sep = "\n\n" if body and not body.endswith("\n\n") else ""
            new_body = (body or "") + sep + content
        new_text = self.render_frontmatter(fields) + "\n" + new_body.lstrip("\n")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + f".tmp.{int(time.time() * 1000)}")
            tmp.write_text(new_text, encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            logger.warning("upsert_long_term 写盘失败 %s: %s", path, exc)

    # ------------------------------------------------------------------
    # L1 工作记忆（真实磁盘 memory/working/<tid>.md，跨调用复用）
    # ------------------------------------------------------------------
    #
    # 设计变更（2026-05-21）：原 plan 把 /working/ 路由到 deepagents StateBackend，
    # 期望 checkpointer 自动持久化。但实测发现：
    # - StateBackend 写到 inner agent 的 state.files channel
    # - inner agent 跨 invoke 重新初始化，files 不被 outer QaAgentState 保留
    # - 结果：第二轮调用时 working notes 已经丢失，注入到模型的 reminder 永远空
    #
    # 改用真实磁盘：append_working / read_working 直接读写
    # `<root>/working/<sanitized_tid>.md`。优点：
    # 1. 跨调用、跨进程、跨 thread 自然持久（不依赖 langgraph state）
    # 2. 用户能 cat memory/working/<tid>.md 直接看到工作记忆，调试方便
    # 3. dream cron 进程能读到（之前承诺不了）
    # 4. 三闸校验照样生效（_resolve_virtual_path 仅校验路径形态）

    def _working_disk_path(self, thread_id: str) -> Path:
        """返回真实磁盘上的 /working/<tid>.md 路径。"""
        # 三闸校验（确保 sanitize 后路径合法）
        virtual = self._resolve_virtual_path(self.working_path(thread_id), for_write=True)
        # virtual 形如 /working/<sanitized>.md，去掉前导 / 拼到 root 下
        rel = virtual.lstrip("/")
        return self._root / rel

    @staticmethod
    def working_path(thread_id: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9_\-.]", "_", thread_id or "default")[:80]
        return f"/working/{sanitized}.md"

    def read_working(self, thread_id: str, *, max_lines: int = 80) -> str:
        """读当前 thread 的工作记忆，返回最近 max_lines 行（尾部）。"""
        try:
            path = self._working_disk_path(thread_id)
        except Exception as exc:
            logger.debug("read_working path resolve 失败: %s", exc)
            return ""
        try:
            if not path.exists():
                return ""
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.debug("read_working 失败: %s", exc)
            return ""
        lines = text.splitlines()
        if len(lines) > max_lines:
            return "\n".join(lines[-max_lines:])
        return text

    def append_working(self, thread_id: str, entry: str) -> None:
        """追加一条 entry 到当前 thread 工作记忆（真实磁盘，原子写入）。

        - 文件不存在则创建（带 frontmatter）
        - 总行数 >200 时从头删到 ≤180（环形截断）
        - try/except 静默，不影响主流程
        """
        if not entry:
            return
        try:
            path = self._working_disk_path(thread_id)
        except Exception as exc:
            logger.debug("append_working path resolve 失败: %s", exc)
            return

        existing = ""
        try:
            if path.exists():
                existing = path.read_text(encoding="utf-8")
        except Exception:
            existing = ""

        fields, body = self.parse_frontmatter(existing) if existing else ({}, "")
        now = self._now_iso()
        if not fields.get("created"):
            fields["created"] = now
            fields["thread_id"] = thread_id
        fields["updated"] = now
        try:
            fields["turn_count"] = str(int(fields.get("turn_count", "0") or "0") + 1)
        except Exception:
            fields["turn_count"] = "1"

        new_entry = (entry or "").rstrip()
        sep = "\n\n" if body and not body.endswith("\n") else "\n"
        new_body = (body or "").rstrip() + sep + new_entry + "\n"

        # 环形截断
        body_lines = new_body.splitlines()
        if len(body_lines) > 200:
            body_lines = body_lines[-180:]
            new_body = "\n".join(body_lines) + "\n"

        new_text = self.render_frontmatter(fields) + "\n" + new_body.lstrip("\n")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + f".tmp.{int(time.time() * 1000)}")
            tmp.write_text(new_text, encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            logger.debug("append_working 写盘失败: %s", exc)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _file_data_to_str(file_data: Any) -> str:
        """把 backend 的 FileData 转字符串（兼容 v1 list[str] 与 v2 str）。"""
        if file_data is None:
            return ""
        if isinstance(file_data, dict):
            content = file_data.get("content")
        else:
            content = getattr(file_data, "content", None)
        if isinstance(content, list):
            return "\n".join(content)
        if isinstance(content, str):
            return content
        return str(content) if content is not None else ""


__all__ = ["MemoryStore"]
