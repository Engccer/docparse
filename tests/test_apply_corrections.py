"""apply_corrections 쪽 한정 치환: hwpx_enrich가 넣는 모든 쪽 주석을 경계로 본다.

hwpx_enrich는 인쇄 쪽 번호가 없으면 `p.pdfN`, `--page-label-rule`이면 `p.Ⅰ-5`·`p.목차 5`처럼
숫자가 아닌 라벨을 쓴다. 이 주석을 경계로 못 보면 그 쪽 본문이 앞 숫자 쪽 구간에 합쳐져
「원본 쪽 2」의 치환이 뒤 라벨 쪽까지 번진다.
"""
from _load import load

A = load("scripts/apply_corrections.py", "apply_corrections")


def run(text, wanted, src="X", dst="Y"):
    segs = A.split_by_page(text)
    segs, n = A.replace_in_pages(segs, wanted, src, dst)
    return "".join(s for _, s in segs), n


def test_label_page_is_a_boundary():
    text = "<!-- p.1 (pdf 1) -->\na\n<!-- p.2 (pdf 2) -->\nX\n<!-- p.Ⅰ-5 (pdf 5) -->\nX\n<!-- p.25 (pdf 25) -->\nX\n"
    out, n = run(text, {2})
    assert n == 1
    assert out.count("X") == 2


def test_pdf_label_page_is_a_boundary():
    text = "<!-- p.12 (pdf 14) -->\nX\n<!-- p.pdf15 (pdf 15) -->\nX\n<!-- p.13 (pdf 16) -->\nb\n"
    out, n = run(text, {12})
    assert n == 1
    assert out.count("X") == 1


def test_numeric_pages_keep_spanning_behavior():
    # 표 한 덩어리가 3~4쪽에 걸치면 4쪽 주석이 없다. 원본 쪽 4는 3쪽 구간에서 찾는다.
    text = "<!-- p.3 (pdf 3) -->\nX\n<!-- p.5 (pdf 5) -->\nX\n"
    out, n = run(text, {4})
    assert n == 1
    assert out == "<!-- p.3 (pdf 3) -->\nY\n<!-- p.5 (pdf 5) -->\nX\n"


def test_label_segment_is_never_targeted_by_number():
    text = "<!-- p.2 (pdf 2) -->\na\n<!-- p.Ⅰ-5 (pdf 5) -->\nX\n"
    out, n = run(text, {5})
    assert n == 0
    assert out == text


def test_old_numeric_forms_still_numeric():
    # 종전 정규식 `p\.(\d+)\b`가 숫자 쪽으로 읽던 모양은 그대로 숫자 쪽이다.
    for mark in ("<!-- p.5 (pdf 7) -->", "<!-- p.5-->", "<!-- p.5-6 -->", "<!-- p.5,pdf7 -->"):
        segs = A.split_by_page(mark + "\nX\n")
        assert segs[1][0] == 5, mark
    assert A.split_by_page("<!-- p.15pdf -->\nX\n")[1][0] is None


def test_numeric_segment_before_label_covers_only_itself():
    # 2쪽 뒤에 라벨 쪽이 이어지면 원본 쪽 5가 2쪽 구간에 걸리지 않는다(쪽 번호를 모르는 라벨 쪽 몫).
    text = "<!-- p.2 (pdf 2) -->\nX\n<!-- p.Ⅰ-5 (pdf 5) -->\nb\n<!-- p.25 (pdf 25) -->\nc\n"
    out, n = run(text, {5})
    assert n == 0
    assert out == text
