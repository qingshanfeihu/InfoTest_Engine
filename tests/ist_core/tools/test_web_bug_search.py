"""kb_bug_search 全平台探测单元测试（无 Playwright）。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from main.ist_core.tools.knowledge import kb_bug_search as wbs


def test_extract_numeric_id_variants():
    assert wbs._extract_numeric_id("12345") == "12345"
    assert wbs._extract_numeric_id("BUG-121100") == "121100"
    assert wbs._extract_numeric_id("plm-998") == "998"
    assert wbs._extract_numeric_id("  #121100 ") == "121100"
    assert wbs._extract_numeric_id("no-digits") is None


def test_fetch_id_for_probe():
    assert wbs._fetch_id_for_probe("12345", "bugzilla") == "BUG-12345"
    assert wbs._fetch_id_for_probe("12345", "zentao") == "PLM-12345"
    assert wbs._fetch_id_for_probe("12345", "zentao_story") == "STORY-12345"
    assert wbs._fetch_id_for_probe("BUG-99", "zentao") == "PLM-99"


def test_web_bug_search_invalid_input():
    assert wbs.kb_bug_search.invoke({"ticket_id": ""})["error_code"] == "invalid_input"
    assert (
        wbs.kb_bug_search.invoke({"ticket_id": "abc"})["error_code"] == "invalid_input"
    )


def test_web_bug_search_single_local_hit():
    fake_ticket = {
        "ticket_id": "BUG-100",
        "title": "t",
        "description": "d",
        "metadata": {"backend": "bugzilla", "severity": "high"},
    }

    def fake_probe(tid: str, backend: str, *, allow_remote: bool):
        if backend == "bugzilla":
            return {
                "outcome": "hit",
                **wbs._summarize_ticket(
                    fake_ticket, source="local_kb", probe_backend=backend
                ),
            }
        return {
            "outcome": "miss",
            "probe_backend": backend,
            "error_code": "not_found",
            "reason": "nope",
        }

    with patch.object(wbs, "_probe_one_backend", side_effect=fake_probe):
        out = wbs.kb_bug_search.invoke({"ticket_id": "100"})

    assert out["status"] == "ok"
    assert out["hits_count"] == 1
    assert out["title"] == "t"
    assert out["ticket_id"] == "BUG-100"
    assert len(out["platform_errors"]) == 2


def test_web_bug_search_multi_platform_hits():
    def make_hit(backend: str, tid: str):
        ticket = {
            "ticket_id": tid,
            "title": f"from-{backend}",
            "description": "",
            "metadata": {"backend": backend},
        }
        return {
            "outcome": "hit",
            **wbs._summarize_ticket(
                ticket, source="local_kb", probe_backend=backend
            ),
        }

    def fake_probe(tid: str, backend: str, *, allow_remote: bool):
        if backend == "bugzilla":
            return make_hit("bugzilla", "BUG-200")
        if backend == "zentao":
            return make_hit("zentao", "PLM-200")
        return {
            "outcome": "miss",
            "probe_backend": backend,
            "error_code": "not_found",
            "reason": "nope",
        }

    with patch.object(wbs, "_probe_one_backend", side_effect=fake_probe):
        out = wbs.kb_bug_search.invoke({"ticket_id": "200"})

    assert out["status"] == "ok"
    assert out["multi_platform"] is True
    assert out["hits_count"] == 2
    assert len(out["results"]) == 2
    backends = {r["probe_backend"] for r in out["results"]}
    assert backends == {"bugzilla", "zentao"}


def test_web_bug_search_all_miss():
    def fake_probe(tid: str, backend: str, *, allow_remote: bool):
        return {
            "outcome": "miss",
            "probe_backend": backend,
            "error_code": "not_found",
            "reason": "missing",
        }

    with patch.object(wbs, "_probe_one_backend", side_effect=fake_probe):
        out = wbs.kb_bug_search.invoke({"ticket_id": "99999"})

    assert out["status"] == "error"
    assert out["error_code"] == "not_found"
    assert len(out["platform_errors"]) == 3
