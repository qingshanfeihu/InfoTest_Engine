"""Tests for main.ingest.html_extractors._common — shared extractor utilities."""

from __future__ import annotations

from main.ingest.html_extractors._common import (
    extract_ticket_id,
    make_soup,
    normalize_resolution,
    normalize_severity,
    normalize_status,
    parse_int,
    select_attrs,
    select_text,
    select_texts,
)


class TestMakeSoup:
    def test_removes_script_and_style(self):
        html = "<html><script>evil()</script><style>.x{}</style><body><p>hello</p></body></html>"
        soup = make_soup(html)
        assert soup.find("script") is None
        assert soup.find("style") is None
        assert soup.find("p").get_text() == "hello"

    def test_removes_nav_header_footer(self):
        html = "<html><nav>nav</nav><header>hdr</header><footer>ftr</footer><p>content</p></html>"
        soup = make_soup(html)
        assert soup.find("nav") is None
        assert soup.find("header") is None
        assert soup.find("footer") is None
        assert "content" in soup.get_text()


class TestSelectText:
    def test_first_match(self):
        html = '<div><span class="title">Bug Title</span></div>'
        soup = make_soup(html)
        assert select_text(soup, [".title"]) == "Bug Title"

    def test_fallback_selector(self):
        html = "<div><p>fallback</p></div>"
        soup = make_soup(html)
        assert select_text(soup, [".missing", "p"]) == "fallback"

    def test_no_match(self):
        html = "<div>text</div>"
        soup = make_soup(html)
        assert select_text(soup, [".missing"]) == ""

    def test_empty_selectors(self):
        html = "<div>text</div>"
        soup = make_soup(html)
        assert select_text(soup, []) == ""


class TestSelectTexts:
    def test_multiple_elements(self):
        html = '<ul><li class="item">A</li><li class="item">B</li></ul>'
        soup = make_soup(html)
        result = select_texts(soup, [".item"])
        assert result == ["A", "B"]

    def test_dedup(self):
        html = '<div><span class="a">X</span><span class="b">X</span></div>'
        soup = make_soup(html)
        result = select_texts(soup, [".a", ".b"])
        assert result == ["X"]


class TestSelectAttrs:
    def test_href(self):
        html = '<a class="link" href="/file.pdf">Download</a>'
        soup = make_soup(html)
        result = select_attrs(soup, [".link"], "href")
        assert result == ["/file.pdf"]

    def test_no_attr(self):
        html = '<a class="link">No href</a>'
        soup = make_soup(html)
        result = select_attrs(soup, [".link"], "href")
        assert result == []


class TestExtractTicketId:
    def test_bug_format(self):
        assert extract_ticket_id("BUG-12345") == "BUG-12345"

    def test_bz_format_normalized(self):
        assert extract_ticket_id("BZ-10001") == "BUG-10001"

    def test_bug_hash_format(self):
        assert extract_ticket_id("Bug #10001") == "BUG-10001"

    def test_story_format(self):
        assert extract_ticket_id("STORY 500") == "STORY-500"

    def test_zentao_normalized(self):
        assert extract_ticket_id("ZENTAO_10002") == "ZT-10002"

    def test_zt_format(self):
        assert extract_ticket_id("ZT-9987") == "ZT-9987"

    def test_plm_format(self):
        assert extract_ticket_id("PLM-123") == "PLM-123"

    def test_plain_text_fallback(self):
        assert extract_ticket_id("just-text") == "just-text"

    def test_empty(self):
        assert extract_ticket_id("") == ""
        assert extract_ticket_id(None) == ""


class TestNormalizeSeverity:
    def test_critical(self):
        for s in ("critical", "Blocker", "P0", "urgent", "S1", "crash"):
            assert normalize_severity(s) == "critical", f"Failed for {s}"

    def test_high(self):
        for s in ("high", "Major", "P1", "S2"):
            assert normalize_severity(s) == "high", f"Failed for {s}"

    def test_mid(self):
        for s in ("medium", "Mid", "normal", "P2", "S3"):
            assert normalize_severity(s) == "mid", f"Failed for {s}"

    def test_low(self):
        for s in ("low", "minor", "P3", "P4", "trivial"):
            assert normalize_severity(s) == "low", f"Failed for {s}"

    def test_empty(self):
        assert normalize_severity("") == "low"
        assert normalize_severity(None) == "low"


class TestNormalizeStatus:
    def test_closed(self):
        for s in ("已关闭", "关闭", "Closed"):
            assert normalize_status(s) == "fixed", f"Failed for {s}"

    def test_fixed(self):
        for s in ("已解决", "已修复", "Fixed", "Resolved", "Done"):
            assert normalize_status(s) == "fixed", f"Failed for {s}"

    def test_open(self):
        for s in ("新建", "new", "active", "open", "待办"):
            assert normalize_status(s) == "open", f"Failed for {s}"

    def test_triage(self):
        assert normalize_status("激活") == "triage"
        assert normalize_status("triage") == "triage"

    def test_empty(self):
        assert normalize_status("") == "open"


class TestNormalizeResolution:
    def test_fixed(self):
        assert normalize_resolution("fixed") == "fixed"
        assert normalize_resolution("已解决") == "fixed"

    def test_duplicate(self):
        assert normalize_resolution("duplicate") == "duplicate"
        assert normalize_resolution("重复") == "duplicate"

    def test_not_repro(self):
        assert normalize_resolution("无法重现") == "not_repro"
        assert normalize_resolution("WORKSFORME") == "not_repro"

    def test_by_design(self):
        assert normalize_resolution("by design") == "by_design"
        assert normalize_resolution("设计如此") == "by_design"

    def test_wont_fix(self):
        assert normalize_resolution("wontfix") == "wont_fix"
        assert normalize_resolution("不予解决") == "wont_fix"

    def test_external(self):
        assert normalize_resolution("外部原因") == "external"

    def test_postponed(self):
        assert normalize_resolution("延期") == "postponed"

    def test_transferred(self):
        assert normalize_resolution("转为需求") == "transferred"

    def test_empty(self):
        assert normalize_resolution("") == ""
        assert normalize_resolution(None) == ""
        assert normalize_resolution("---") == ""
        assert normalize_resolution("none") == ""

    def test_unknown_passthrough(self):
        assert normalize_resolution("some_custom") == "some_custom"


class TestParseInt:
    def test_valid(self):
        assert parse_int("42") == 42
        assert parse_int(10) == 10

    def test_invalid(self):
        assert parse_int("abc") == 0
        assert parse_int("abc", default=-1) == -1

    def test_none(self):
        assert parse_int(None) == 0
        assert parse_int(None, default=5) == 5

    def test_whitespace(self):
        assert parse_int("  7  ") == 7
