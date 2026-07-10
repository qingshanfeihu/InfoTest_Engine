"""决策史存储(DESIGN §11.11 构件三):knowledge/adjudications/<slug>.md。

人源专属(THEORY §2.6 A5):写入口是**纯函数**——不做 @tool、不进任何注册表/白名单,
只有引擎的 ask_contradiction 节点在拿到用户 decision 后调用。fork/主 agent 无路径可写,
这比"注册了但白名单不含"更强(不存在配置漂移面)。

形态:md + frontmatter(判例键+锚),与 memory/ 同构——人可读、git 可 diff、可手工纠错。
检索:find_adjudications 线性扫描(决策史存量≈0,user_decision.json 存档 0 个;FTS5 在
这个量级是过度工程)。若积累到百级,把本模块接入 kb_memory_search 同款 FTS5 底座即可
(md=事实源不变,索引只是缓存)。
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9-]+")

# 判例键三元组(§2.6 A3);写入前逐项非空校验
KEY_FIELDS = ("intent_signature", "conflict_shape", "version_family")


def adjudications_root() -> Path:
    return Path(__file__).resolve().parents[4] / "knowledge" / "adjudications"


def adjudication_slug(key: dict) -> str:
    """判例键 → 语义 slug(官方实践:可读 slug 显著优于裸 hash 的检索精度)。"""
    parts = [str(key.get(k) or "").strip().lower() for k in KEY_FIELDS]
    joined = "--".join(_SLUG_RE.sub("-", p).strip("-") for p in parts)
    return joined[:180] or "unkeyed"


def write_adjudication(key: dict, ruling: str, anchor: dict,
                       sides: list[dict] | None = None,
                       meta: dict | None = None) -> Path:
    """落一条用户裁决(plan-validate-execute:构 md → 验证 → 原子写)。

    key: {intent_signature, conflict_shape, version_family}(全必填)
    ruling: 中文裁决正文(用户答案原文;confirm 时调用方拼入引擎理解)
    anchor: {version, lineage}(ts 本函数补)——应然锚(§2.6 A2)必填
    sides: 原 panel 的双方记载(含 device 侧引文——采信时与新回显机械比对的素材)
    meta: {autoid, batch, token} 等溯源字段
    同键碰撞 → 追加 Revision 段(不覆盖;anchor.ts 更新为最新)。
    """
    for k in KEY_FIELDS:
        if not str(key.get(k) or "").strip():
            raise ValueError(f"adjudication key.{k} is required")
    if not (ruling or "").strip():
        raise ValueError("adjudication ruling is required")
    if not str((anchor or {}).get("lineage") or "").strip():
        raise ValueError("adjudication anchor.lineage is required (e.g. user_proxy)")

    root = adjudications_root()
    root.mkdir(parents=True, exist_ok=True)
    slug = adjudication_slug(key)
    path = root / f"{slug}.md"
    ts = _dt.datetime.now().isoformat(timespec="seconds")
    anchor = {**(anchor or {}), "ts": ts}

    fm = {k: str(key.get(k)).strip() for k in KEY_FIELDS}
    fm["anchor"] = anchor
    for mk, mv in (meta or {}).items():
        fm[str(mk)] = mv

    side_lines = []
    for s in (sides or []):
        src = str(s.get("source_ref") or "")
        side_lines.append(f"- [{src}] 『{str(s.get('quote') or '')[:600]}』"
                          + (f"(锚:{s.get('anchor')})" if s.get("anchor") else ""))

    if path.is_file():
        # 同键碰撞:保留全史,追加 revision;frontmatter 只更新 anchor(最新裁决时点)
        old = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", old, re.DOTALL)
        if m:
            try:
                old_fm = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                old_fm = {}
            old_fm["anchor"] = anchor
            if meta:
                old_fm.update({str(mk): mv for mk, mv in meta.items()})
            body = old[m.end():]
            new_fm = yaml.safe_dump(old_fm, allow_unicode=True, sort_keys=False).strip()
            text = (f"---\n{new_fm}\n---\n{body.rstrip()}\n\n"
                    f"## Revision @{ts}\n\n{ruling.strip()}\n")
            if side_lines:
                text += "\n" + "\n".join(side_lines) + "\n"
        else:
            text = old.rstrip() + f"\n\n## Revision @{ts}\n\n{ruling.strip()}\n"
        path.write_text(text, encoding="utf-8")
        logger.info("adjudication revision appended: %s", path.name)
        return path

    fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    text = f"---\n{fm_text}\n---\n\n# 裁决\n\n{ruling.strip()}\n"
    if side_lines:
        text += "\n## 双方记载\n\n" + "\n".join(side_lines) + "\n"
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    logger.info("adjudication written: %s", path.name)
    return path


def find_adjudications(intent_signature: str = "", conflict_shape: str = "",
                       version_family: str = "", query: str = "") -> list[dict]:
    """键查/关键词查决策史。返回 [{slug, path, body, <frontmatter…>}],新裁决在前。

    键字段给了就精确匹配(判例键失配保守回落 ask——§2.6 A3);query 是正文包含查
    (裁决史小语料,包含查足够)。
    """
    root = adjudications_root()
    if not root.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(root.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if intent_signature and str(fm.get("intent_signature")) != intent_signature.strip().lower():
            continue
        if conflict_shape and str(fm.get("conflict_shape")) != conflict_shape.strip().lower():
            continue
        if version_family and str(fm.get("version_family")) != str(version_family).strip():
            continue
        body = text[m.end():]
        if query and query.strip():
            terms = [t for t in re.split(r"\s+", query.strip()) if t]
            if not any(t in text for t in terms):   # OR 语义,与其他检索源一致
                continue
        out.append({"slug": p.stem, "path": str(p), "body": body.strip(), **fm})
    out.sort(key=lambda d: str((d.get("anchor") or {}).get("ts") or ""), reverse=True)
    return out
