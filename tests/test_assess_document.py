"""assess_document.rule_hints: SKILL.md가 ◇로 약속한 「≤20p 시각 렌더링」 힌트는 쪽수로 건다.

티어로 걸면 16~20쪽 문서와(텍스트 레이어가 없으면 티어가 한 단계 오르므로) 15쪽 이하 스캔본이 빠진다.
"""
from _load import load

D = load("scripts/assess_document.py", "assess_document")
SIG = {"sampled_pages": [1], "text_pages": 1, "pua_per_10k": 0.0, "latin_ratio": 0.0}
READ = "PDF Read 도구의 시각 렌더링 = ground truth (≤20p)"


def test_read_hint_for_18_pages_medium():
    assert READ in D.rule_hints("pdf", "medium", True, False, SIG, "ko", pages=18)


def test_read_hint_for_12_page_scan_bumped_to_medium():
    sig = dict(SIG, text_pages=0)
    assert READ in D.rule_hints("pdf", "medium", False, False, sig, "ko", pages=12)


def test_no_read_hint_over_20_pages():
    assert READ not in D.rule_hints("pdf", "medium", True, False, SIG, "ko", pages=21)


def test_main_passes_page_count_to_hints(tmp_path, monkeypatch, capsys):
    import json
    import sys
    try:
        import pymupdf
    except ImportError:  # 구버전은 fitz만 있다
        import fitz as pymupdf
    for n, want in ((18, True), (21, False)):
        pdf = tmp_path / f"d{n}.pdf"
        doc = pymupdf.open()
        for i in range(n):
            doc.new_page().insert_text((72, 72), f"page {i + 1} 본문 텍스트 레이어")
        doc.save(pdf)
        monkeypatch.setattr(sys, "argv", ["assess_document.py", str(pdf)])
        assert D.main() == 0
        out = json.loads(capsys.readouterr().out)
        assert (READ in out["rule_hints"]) is want, (n, out["rule_hints"])


def test_odt_is_supported_and_routed_to_openai():
    assert D.SUPPORTED_FORMATS[".odt"] == "odt"
    assert D.recommend_parsers("odt", "odt", True, False) == ["openai"]


def test_main_assigns_odt_tier(tmp_path, monkeypatch, capsys):
    import json
    import sys
    odt = tmp_path / "공문.odt"
    odt.write_bytes(b"PK")
    monkeypatch.setattr(sys, "argv", ["assess_document.py", str(odt)])
    assert D.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["format"] == "odt"
    assert out["tier"] == "odt"
    assert out["recommended_parsers"] == ["openai"]
    assert any("content.xml" in h for h in out["rule_hints"])


def test_openai_parser_accepts_odt():
    P = load("parsers/openai_parse.py", "openai_parse")
    assert P.OFFICE_MIME[".odt"] == "application/vnd.oasis.opendocument.text"
    assert ".odt" in P.SUPPORTED_EXT


def test_odt_hint_names_pandoc_loss_and_metadata_title():
    hints = D.rule_hints("odt", "odt", True, False, SIG, "ko")
    assert any("Pandoc" in h and "content.xml" in h for h in hints)
    assert any("dc:title" in h for h in hints)
