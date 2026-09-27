"""apply_corrections 쪽 한정 치환.

hwpx_enrich는 인쇄 쪽 번호가 없으면 `p.pdfN`, `--page-label-rule`이면 `p.Ⅰ-5`처럼 숫자가 아닌
라벨을 쓴다. 숫자로 시작하는 주석만 경계이고, 라벨 쪽 본문은 앞 숫자 쪽 구간에 속한다(주석 없는 쪽과 같음).
라벨을 경계로 삼으면 간지(번호 없는 쪽) 뒤 본문을 숫자 원본 쪽으로 지정할 수 없게 된다.
"""
import csv
import sys

from _load import load

A = load("scripts/apply_corrections.py", "apply_corrections")


def run(text, wanted, src="X", dst="Y"):
    segs = A.split_by_page(text)
    segs, n = A.replace_in_pages(segs, wanted, src, dst)
    return "".join(s for _, s in segs), n


def test_label_page_body_belongs_to_preceding_numeric_page():
    # 간지(p.pdf15) 뒤 인쇄 14쪽 본문을 원본 쪽 14로 지정할 수 있다.
    text = ("<!-- p.3 (pdf 5) -->\n## 1. 절\n본문\n<!-- p.pdf15 (pdf 15) -->\n# Ⅱ. 장\n"
            "장 도입 2025년 오인식\n<!-- p.25 (pdf 25) -->\n2025년 정상\n")
    out, n = run(text, {14}, "2025년 오인식", "2024년 오인식")
    assert n == 1
    assert "2025년 정상" in out


def test_numeric_pages_keep_spanning_behavior():
    # 표 한 덩어리가 3~4쪽에 걸치면 4쪽 주석이 없다. 원본 쪽 4는 3쪽 구간에서 찾는다.
    text = "<!-- p.3 (pdf 3) -->\nX\n<!-- p.5 (pdf 5) -->\nX\n"
    out, n = run(text, {4})
    assert n == 1
    assert out == "<!-- p.3 (pdf 3) -->\nY\n<!-- p.5 (pdf 5) -->\nX\n"


def test_pdf_prefixed_original_page_is_not_a_printed_page():
    # pdf15의 뒷자리 5가 인쇄 쪽 5로 새면 엉뚱한 쪽을 조용히 치환한다.
    assert A.printed_pages("pdf15") == set()
    assert A.printed_pages("pdf123") == set()
    assert A.printed_pages("12, pdf15") == {12}
    assert A.printed_pages("pdf7") == set()
    assert A.printed_pages("pdf5, 5") == {5}
    assert A.printed_pages("5, 6 외") == {5, 6}


def test_main_sends_pdf_prefixed_page_to_global_path(tmp_path, monkeypatch):
    # 원본 쪽 `pdf16`은 인쇄 쪽 6이 아니다: 6쪽만 바꾸지 않고 전역 치환(경고)으로 간다.
    md = tmp_path / "in.md"
    md.write_text("<!-- p.5 (pdf 7) -->\n2025년\n<!-- p.6 (pdf 8) -->\n2025년\n", encoding="utf-8")
    rows = [{"문서": "D", "원본 쪽": "pdf16", "원문": "2025년", "수정문": "2024년",
             "유형": "오탈자", "처리": "적용", "근거": "", "비고": ""}]
    with open(tmp_path / "c.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=A.COLS)
        w.writeheader()
        w.writerows(rows)
    out = tmp_path / "out.md"
    monkeypatch.setattr(sys, "argv", ["apply_corrections.py", "--csv", str(tmp_path / "c.csv"), "--doc", "D",
                                      "--in", str(md), "--out", str(out)])
    A.main()
    assert out.read_text(encoding="utf-8").count("2024년") == 2
