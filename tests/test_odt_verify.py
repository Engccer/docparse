"""합성 ODT 회귀 자료로 content.xml 문단 전수 대조(odt_verify.py)를 시험한다. 네트워크 없음."""
import json
import shutil
import subprocess
import sys

import pytest
from _load import ROOT, load

F = load("scripts/make_odt_fixtures.py", "make_odt_fixtures")
V = load("scripts/odt_verify.py", "odt_verify")
A = load("scripts/assess_document.py", "assess_document_odt")


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    out = tmp_path_factory.mktemp("odt")
    for name in F.FIXTURES:
        F.build(name, out)
    return out


def ref(fx, name):
    return (fx / f"{name}.reference.md").read_text(encoding="utf-8")


def check(fx, name, md):
    return V.verify(fx / f"{name}.odt", md)


@pytest.mark.parametrize("name", list(F.FIXTURES))
def test_reference_output_passes(fx, name):
    r = check(fx, name, ref(fx, name))
    assert r["verdict"] == "PASS", r
    assert r["paragraphs"] > 0


def test_fixtures_are_byte_for_byte_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    for name in F.FIXTURES:
        assert F.build(name, a).read_bytes() == F.build(name, b).read_bytes()


def test_fixtures_have_no_real_contact_data(fx):
    text = "".join(ref(fx, n) for n in F.FIXTURES)
    emails = [w for w in text.replace("/", " ").split() if "@" in w]
    assert emails and all(e.endswith("@example.com") for e in emails)


def test_source_structure_is_read_from_xml(fx):
    src = V.read_odt(fx / "table_header_merge.odt")
    rows = src["tables"][0]["rows"]
    assert rows[0] == {"header": True, "cells": ["학년", "학급", "1학기", "2학기"]}
    assert rows[2]["cells"] == ["2반", "98권", "104권 (추정)"]  # rowspan으로 가려진 칸은 건너뜀
    assert rows[4]["cells"] == ["합계", "210권", "234권"]  # colspan
    gm = V.read_odt(fx / "gongmun.odt")
    assert "수신 수신자 참조" in gm["paragraphs"]  # text:s 공백 복원
    assert "※ 회의 자료는 사전에 배포합니다." in gm["paragraphs"]  # 글상자 안 문단
    assert gm["header_footer"] == ["가상시 교육지원청 내부 문서", "가상시 교육지원청"]


def test_missing_textbox_paragraph_fails(fx):
    md = ref(fx, "gongmun").replace("※ 회의 자료는 사전에 배포합니다.\n", "")
    r = check(fx, "gongmun", md)
    assert r["verdict"] == "FAIL"
    assert r["missing"] == ["※ 회의 자료는 사전에 배포합니다."]


def test_dropped_header_row_is_reported_as_header(fx):
    """Mistral 실측 양상: 표 머리행 통째 소실, 짧은 문단 병합."""
    md = ref(fx, "gongmun").replace("| 구분 | 일시 | 장소 |\n", "")
    md = md.replace("수신  수신자 참조\n\n(경유)\n\n제목", "수신  수신자 참조 (경유) 제목")
    r = check(fx, "gongmun", md)
    assert r["verdict"] == "FAIL"
    assert [(t["table"], t["row"], t["header"]) for t in r["table_rows"]] == [(1, 1, True)]
    assert r["missing"] == ["구분", "일시", "장소"]
    assert r["order"] == []  # 병합된 수신·제목은 글과 순서가 그대로라 통과


def test_flattened_table_row_fails_cell_correspondence(fx):
    md = ref(fx, "gongmun").replace("| 2차 회의 | 2026. 1. 12. 14:00 | 온라인 |", "| 2차 회의 |\n\n2026. 1. 12. 14:00 온라인")
    r = check(fx, "gongmun", md)
    assert [(t["row"], t["header"]) for t in r["table_rows"]] == [(3, False)]


def test_reordered_paragraphs_fail(fx):
    md = ref(fx, "metadata_placeholder")
    a, b = "겨울방학 방과후 수업 신청을 받습니다.", "신청 기간: 2026. 1. 6. ~ 1. 9."
    md = md.replace(a, "@@").replace(b, a).replace("@@", b)
    r = check(fx, "metadata_placeholder", md)
    assert r["verdict"] == "FAIL" and r["order"]


def test_duplicated_paragraph_fails(fx):
    line = "2. 아래와 같이 점검 회의를 열고자 하니 협조하여 주시기 바랍니다."
    md = ref(fx, "gongmun").replace(line, line + "\n\n" + line)
    r = check(fx, "gongmun", md)
    assert r["verdict"] == "FAIL"
    assert r["duplicates"][0]["output"] == 2


def test_metadata_placeholder_leak_fails(fx):
    md = F.PLACEHOLDER + "\n\n" + ref(fx, "metadata_placeholder")
    r = check(fx, "metadata_placeholder", md)
    assert r["verdict"] == "FAIL"
    assert r["metadata_leaks"] == [{"text": F.PLACEHOLDER, "source_body": 0, "output": 1}]


def test_placeholder_that_is_real_body_text_is_kept(fx):
    """같은 문구라도 본문에 실제로 있으면 그 횟수까지는 정상(문자열 무조건 삭제 금지)."""
    md = ref(fx, "placeholder_in_body")
    assert check(fx, "placeholder_in_body", md)["metadata_leaks"] == []
    r = check(fx, "placeholder_in_body", F.PLACEHOLDER + "\n\n" + md)
    assert r["metadata_leaks"] == [{"text": F.PLACEHOLDER, "source_body": 1, "output": 2}]


def test_images_are_reported_separately_from_text_verdict(fx):
    md = "\n".join(l for l in ref(fx, "image_caption").splitlines() if not l.startswith("!["))
    r = check(fx, "image_caption", md)
    assert r["verdict"] == "PASS"
    assert r["images"] == {"embedded": 1, "output_refs": 0, "extracted_refs": 0, "status": "not_extracted"}
    assert "미추출" in V.render(r)
    assert check(fx, "gongmun", ref(fx, "gongmun"))["images"]["status"] == "none"


def test_reference_to_path_inside_odt_is_not_extraction(fx):
    """Pandoc은 이미지를 꺼내지 않고 ODT 안 경로만 가리킨다."""
    r = check(fx, "image_caption", ref(fx, "image_caption"))
    assert r["images"]["output_refs"] == 1 and r["images"]["status"] == "not_extracted"
    md = ref(fx, "image_caption").replace("(Pictures/layout.png)", "(media/layout.png)")
    assert check(fx, "image_caption", md)["images"]["status"] == "referenced"


def test_footnote_body_is_checked_for_presence_not_position(fx):
    r = check(fx, "image_caption", ref(fx, "image_caption"))
    assert r["verdict"] == "PASS" and r["notes"] == 1
    md = ref(fx, "image_caption").replace("[^1]: 합성 각주: 이미지 내용은 따로 판독한다.", "")
    assert check(fx, "image_caption", md)["missing"] == ["합성 각주: 이미지 내용은 따로 판독한다."]


def test_printed_footer_is_not_a_duplicate(fx):
    md = ref(fx, "gongmun") + "\n가상시 교육지원청 내부 문서\n\n가상시 교육지원청\n"
    r = check(fx, "gongmun", md)
    assert r["verdict"] == "PASS", r
    assert all(h["in_output"] for h in r["header_footer"])


def test_underscore_blanks_match_raw_and_escaped(fx):
    md = ref(fx, "placeholder_in_body")
    assert check(fx, "placeholder_in_body", md)["verdict"] == "PASS"
    escaped = md.replace("________", "\\_" * 8)
    assert check(fx, "placeholder_in_body", escaped)["verdict"] == "PASS"


@pytest.mark.parametrize("link", ["<office@example.com>", "[office@example.com](mailto:office@example.com)",
                                  '<a href="mailto:office@example.com">office@example.com</a>'])
def test_links_in_contact_line_are_normalized(fx, link):
    md = ref(fx, "gongmun").replace("office@example.com", link)
    assert check(fx, "gongmun", md)["verdict"] == "PASS"


def test_table_cell_spacing_difference_is_reported_not_failed(fx):
    md = ref(fx, "gongmun").replace("| 1차 회의 |", "| 1차회의 |")
    r = check(fx, "gongmun", md)
    assert r["verdict"] == "PASS"
    assert [(t["table"], t["row"]) for t in r["spacing_rows"]] == [(1, 2)]


def test_bookmark_name_leak_fails(fx):
    md = "여기에 제목 입력\n\n" + ref(fx, "metadata_placeholder")
    assert [m["text"] for m in check(fx, "metadata_placeholder", md)["metadata_leaks"]] == ["여기에 제목 입력"]


def test_spacing_only_difference_is_reported_not_failed(fx):
    md = ref(fx, "gongmun").replace("수신  수신자 참조", "수신수신자 참조")
    r = check(fx, "gongmun", md)
    assert r["verdict"] == "PASS"
    assert r["spacing_only"] == ["수신 수신자 참조"]


def test_markdown_escapes_and_html_rows_are_normalized(fx):
    md = ref(fx, "gongmun").replace("<붙임>", "\\<붙임\\>").replace("1. 관련", "1\\. 관련")
    assert check(fx, "gongmun", md)["verdict"] == "PASS"
    multi_line = ref(fx, "table_header_merge").replace("</td><td", "</td>\n<td")
    assert check(fx, "table_header_merge", multi_line)["verdict"] == "PASS"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc 없음")
def test_pandoc_alone_silently_drops_textbox(fx):
    md = subprocess.run(["pandoc", "-f", "odt", "-t", "gfm", str(fx / "gongmun.odt")],
                        capture_output=True, text=True, check=True).stdout
    r = check(fx, "gongmun", md)
    assert r["verdict"] == "FAIL"
    assert "※ 회의 자료는 사전에 배포합니다." in r["missing"]


def test_cli_exit_codes(fx, tmp_path):
    script = str(ROOT / "scripts/odt_verify.py")
    good = fx / "gongmun.reference.md"
    bad = tmp_path / "bad.md"
    bad.write_text("빈 결과", encoding="utf-8")
    run = lambda *a: subprocess.run([sys.executable, script, *map(str, a)], capture_output=True, text=True)
    ok = run(fx / "gongmun.odt", good, "--json")
    assert ok.returncode == 0 and json.loads(ok.stdout)["verdict"] == "PASS"
    assert run(fx / "gongmun.odt", bad).returncode == 1
    assert run(bad, good).returncode == 2  # zip 아님
    assert run(fx / "gongmun.odt").returncode == 2


def test_fixture_cli_rejects_unknown_name(tmp_path):
    script = str(ROOT / "scripts/make_odt_fixtures.py")
    r = subprocess.run([sys.executable, script, str(tmp_path), "없는자료"], capture_output=True, text=True)
    assert r.returncode == 2


def test_assess_reports_embedded_images(fx, tmp_path):
    assert A.odt_embedded_images(fx / "image_caption.odt") == 1
    assert A.odt_embedded_images(fx / "gongmun.odt") == 0
    not_zip = tmp_path / "x.odt"
    not_zip.write_bytes(b"PK")
    assert A.odt_embedded_images(not_zip) is None
    signals = {"embedded_images": 1}
    hints = A.rule_hints("odt", "odt", True, False, signals, "ko")
    assert any("내장 이미지 1개" in h for h in hints)


def test_short_unique_paragraphs_keep_order_check(fx):
    """짧은 문단도 원본·출력에 한 번씩만 나오면 순서를 본다(제목 자리 바꿈 검출)."""
    md = ref(fx, "gongmun").replace("(경유)\n", "")
    md = md.rstrip("\n") + "\n\n(경유)\n"
    r = check(fx, "gongmun", md)
    assert r["verdict"] == "FAIL" and r["order"] and not r["missing"]


def test_superscript_footnote_marker_is_normalized(fx):
    md = ref(fx, "image_caption").replace("않는다.[^1]", "않는다.¹").replace("[^1]: ", "¹ ")
    assert check(fx, "image_caption", md)["verdict"] == "PASS"


def test_placeholder_image_ref_still_prompts_visual_check(fx):
    md = ref(fx, "image_caption").replace("(Pictures/layout.png)", "(img-0.jpeg)")
    r = check(fx, "image_caption", md)
    assert r["images"]["status"] == "referenced"
    assert "따로 판독" in V.render(r)
