"""assess_document.rule_hints: SKILL.md가 ◇로 약속한 「≤20p 시각 렌더링」 힌트는 쪽수로 건다.

티어로 걸면 16~20쪽 문서와(텍스트 레이어가 없으면 티어가 한 단계 오르므로) 15쪽 이하 스캔본이 빠진다.
"""
from _load import load

D = load("scripts/assess_document.py", "assess_document")
SIG = {"sampled_pages": [1], "text_pages": 1, "pua_per_10k": 0.0, "latin_ratio": 0.0}
READ = "PDF 시각 판독 = ground truth (≤20p)"


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
    assert D.recommend_parsers("odt", "odt", True, False) == ["openai", "mistral"]


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
    assert out["recommended_parsers"] == ["openai", "mistral"]
    assert any("content.xml" in h for h in out["rule_hints"])


def test_mistral_parser_accepts_odt():
    M = load("parsers/mistral_parse.py", "mistral_parse")
    assert M.MIME_TYPES[".odt"] == "application/vnd.oasis.opendocument.text"


def test_openai_parser_accepts_odt():
    P = load("parsers/openai_parse.py", "openai_parse")
    assert P.OFFICE_MIME[".odt"] == "application/vnd.oasis.opendocument.text"
    assert ".odt" in P.SUPPORTED_EXT


def test_odt_hint_names_pandoc_loss_and_metadata_title():
    hints = D.rule_hints("odt", "odt", True, False, SIG, "ko")
    assert any("Pandoc" in h and "content.xml" in h for h in hints)
    assert any("dc:title" in h for h in hints)


def test_hwpx_underline_signal_and_hint(tmp_path, monkeypatch, capsys):
    """HWPX 밑줄 run·공백 빈칸을 세고, 있으면 --underline을 권한다(합성 HWPX)."""
    import json
    import sys
    from hwpx_fixture import SPAN_ONLY, TAB_BLANK, make_hwpx, run

    assert D.hwpx_underline(make_hwpx(tmp_path / "a.hwpx")) == {"underline_runs": 3, "underline_blanks": 1}
    plain = make_hwpx(tmp_path / "b.hwpx", body="<hp:p>" + run(0, "밑줄 없음") + "</hp:p>")
    assert D.hwpx_underline(plain) == {"underline_runs": 0, "underline_blanks": 0}
    assert D.hwpx_underline(make_hwpx(tmp_path / "c.hwpx", header=False)) == {"underline_runs": 0, "underline_blanks": 0}
    (tmp_path / "broken.hwpx").write_bytes(b"not a zip")
    assert D.hwpx_underline(tmp_path / "broken.hwpx") is None

    # 탭 밑줄 빈칸: 엔진처럼 tab을 공백으로 읽어 빈칸 후보로 센다
    tab = make_hwpx(tmp_path / "t.hwpx", body=TAB_BLANK)
    assert D.hwpx_underline(tab) == {"underline_runs": 1, "underline_blanks": 1}
    span_only = make_hwpx(tmp_path / "s.hwpx", body=SPAN_ONLY)

    def hints(path):
        monkeypatch.setattr(sys, "argv", ["assess_document.py", str(path)])
        assert D.main() == 0
        return " ".join(json.loads(capsys.readouterr().out)["rule_hints"])

    assert "자동으로 켠다" in hints(tmp_path / "a.hwpx")
    assert "--underline" in hints(span_only) and "자동" not in hints(span_only)
    assert "밑줄" not in hints(plain)


def _image_pdf(path, pages, px, share=0.5, text="CLASS 150 FLANGES 제목 글자층은 있다 " * 3):
    """글자층(제목)과 내장 이미지가 함께 있는 합성 PDF. px=(가로, 세로) 픽셀, share=쪽 면적 대비 이미지 비율."""
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=720, height=540)
        page.insert_text((40, 40), text)
        if px:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, px[0], px[1]), False)
            pix.clear_with(180)
            page.insert_image(pymupdf.Rect(40, 60, 40 + 640, 60 + 540 * share * 720 / 640), pixmap=pix)
    doc.save(path)
    return path


def _assess(path, monkeypatch, capsys):
    import json
    import sys
    monkeypatch.setattr(sys, "argv", ["assess_document.py", str(path)])
    assert D.main() == 0
    return json.loads(capsys.readouterr().out)


def test_low_resolution_image_pages_are_reported(tmp_path, monkeypatch, capsys):
    """글자층이 있어도 쪽의 절반이 100DPI 안팎 이미지면 신호와 힌트로 드러낸다(표가 이미지로 박힌 카탈로그)."""
    out = _assess(_image_pdf(tmp_path / "lowres.pdf", 4, (640 * 100 // 72, 300 * 100 // 72)), monkeypatch, capsys)
    assert out["has_text_layer"] is True
    sig = out["signals"]
    assert sig["image_pages"] == 4
    assert sig["low_dpi_image_pages"] == 4
    assert 95 <= sig["image_dpi_median"] <= 105
    hints = " ".join(out["rule_hints"])
    assert "글자층은 있지만 표·본문이 이미지인 PDF" in hints
    assert "저해상도" in hints


def test_high_resolution_image_pages_get_image_hint_without_low_dpi(tmp_path, monkeypatch, capsys):
    out = _assess(_image_pdf(tmp_path / "hires.pdf", 4, (640 * 300 // 72, 300 * 300 // 72)), monkeypatch, capsys)
    sig = out["signals"]
    assert sig["image_pages"] == 4 and sig["low_dpi_image_pages"] == 0
    hints = " ".join(out["rule_hints"])
    assert "글자층은 있지만 표·본문이 이미지인 PDF" in hints
    assert "저해상도" not in hints


def test_text_only_pdf_has_no_image_hint(tmp_path, monkeypatch, capsys):
    out = _assess(_image_pdf(tmp_path / "text.pdf", 4, None), monkeypatch, capsys)
    sig = out["signals"]
    assert sig["image_pages"] == 0 and sig["low_dpi_image_pages"] == 0 and sig["image_dpi_median"] is None
    assert "이미지인 PDF" not in " ".join(out["rule_hints"])


def test_small_logo_images_are_ignored(tmp_path, monkeypatch, capsys):
    """쪽 면적의 5% 미만인 로고·아이콘은 세지 않는다."""
    out = _assess(_image_pdf(tmp_path / "logo.pdf", 4, (60, 20), share=0.03), monkeypatch, capsys)
    assert out["signals"]["image_pages"] == 0


def test_image_document_hint_needs_30_percent_of_sample():
    """표본의 30% 이상이 이미지 쪽일 때만 '표·본문이 이미지인 PDF'로 알리고, 그 아래는 일부 쪽 알림이다."""
    def hints(image_pages):
        sig = dict(SIG, sampled_pages=list(range(1, 11)), image_pages=image_pages,
                   low_dpi_image_pages=0, image_dpi_median=200)
        return " ".join(D.rule_hints("pdf", "medium", True, False, sig, "ko", pages=40))
    assert "표·본문이 이미지인 PDF" in hints(3)
    assert "표·본문이 이미지인 PDF" not in hints(2) and "일부 쪽에 큰 이미지" in hints(2)
    assert "이미지" not in hints(0)


def test_help_is_not_taken_as_a_file_path():
    import subprocess
    import sys
    from _load import ROOT
    for flag in ("--help", "-h"):
        run = subprocess.run([sys.executable, str(ROOT / "scripts" / "assess_document.py"), flag],
                             capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        assert run.returncode == 0 and "사용법" in run.stdout and "찾을 수 없습니다" not in run.stdout
