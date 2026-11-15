"""hwpx_local_parse.py 밑줄 보존: hwpx-tomd 0.5.0 연결(합성 HWPX, 네트워크 없음).

불변식: 엔진이 밑줄 빈칸(\\_)을 하나라도 내면 밑줄 보존을 자동으로 켜고, 장식 밑줄만 있는 문서는 출력이
종전과 같다. --underline은 빈칸이 없어도 켠다. 설치된 엔진이 underline 인자를 모르면 밑줄 없이 변환하고
안내한다(출력·종료 코드 0 유지).
"""
import inspect
import sys

import pytest

from _load import load
from hwpx_fixture import BLANK, SPAN, SPAN_ONLY, make_hwpx, run

hwpx_tomd = pytest.importorskip("hwpx_tomd")
P = load("parsers/hwpx_local_parse.py", "hwpx_local_parse")
needs_underline = pytest.mark.skipif(
    "underline" not in inspect.signature(hwpx_tomd.convert).parameters, reason="hwpx-tomd 0.5.0 미만"
)


def run_main(monkeypatch, path, *flags):
    monkeypatch.setattr(sys, "argv", ["hwpx_local_parse.py", str(path), *flags])
    code = P.main()
    out = path.with_name(path.stem + "_hwpxlocal.md")
    return code, out.read_text(encoding="utf-8") if out.exists() else None


@needs_underline
def test_blank_auto_enables_underline(tmp_path, monkeypatch, capsys):
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "exam.hwpx"))
    assert code == 0
    assert f"I am {BLANK} to school." in md
    assert f"2. (A) {SPAN} 중 어법상 틀린 것은?" in md
    out = capsys.readouterr().out
    assert "밑줄 빈칸 6칸 발견" in out and "밑줄 표시가" not in out


def test_decorative_underline_only_keeps_plain_output(tmp_path, monkeypatch):
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "doc.hwpx", body=SPAN_ONLY))
    assert code == 0
    assert "<u>" not in md and "\\_" not in md
    assert "2. (A) 밑줄 친 부분 중 어법상 틀린 것은?" in md


@needs_underline
def test_manual_flag_enables_without_blanks(tmp_path, monkeypatch):
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "doc.hwpx", body=SPAN_ONLY), "--underline")
    assert code == 0 and SPAN in md


def test_old_engine_falls_back_with_notice(tmp_path, monkeypatch, capsys):
    real = hwpx_tomd.convert

    def old_convert(filepath, *, cell_br=False, merge_fill=False):  # 0.4.x 시그니처
        return real(filepath, cell_br=cell_br, merge_fill=merge_fill)

    monkeypatch.setattr(hwpx_tomd, "convert", old_convert)
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "exam.hwpx"), "--underline")
    assert code == 0
    assert "<u>" not in md and "\\_" not in md
    assert "hwpx-tomd>=0.5.0" in capsys.readouterr().out


@needs_underline
def test_underline_guard_warning_keeps_output(tmp_path, monkeypatch, capsys):
    real = hwpx_tomd.convert

    def lossy(filepath, *, underline=False, **kw):  # 시그니처 검사가 0.5.0으로 보도록 underline을 명시
        res = real(filepath, underline=underline, **kw)
        if underline:
            res.warnings.append("밑줄 표시가 렌더링 중 누락되었습니다: 밑줄 빈칸 6칸. 확인하세요.")
        return res

    monkeypatch.setattr(hwpx_tomd, "convert", lossy)
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "exam.hwpx"))
    assert code == 0 and md
    assert "경고: 밑줄 표시가" in capsys.readouterr().out


@needs_underline
def test_guard_prefix_matches_engine_wording():
    """엔진이 문구를 바꾸면 경고가 [알림]으로 내려가므로 실제 문구로 묶어 둔다."""
    from hwpx_tomd import core

    assert core._underline_loss([["밑줄"]], "").startswith(P.UNDERLINE_GUARD_PREFIX[0])
    assert P.UNDERLINE_BLANK == core._UL_BLANK


@needs_underline
def test_decorative_output_identical_to_plain_convert(tmp_path, monkeypatch):
    path = make_hwpx(tmp_path / "doc.hwpx", body=SPAN_ONLY)
    _, md = run_main(monkeypatch, path)
    assert md == hwpx_tomd.convert(path).markdown


@needs_underline
def test_literal_backslash_underscore_does_not_trigger(tmp_path, monkeypatch, capsys):
    """원문 글자 `\\_`(경로·LaTeX)는 엔진이 이스케이프하지 않아 기준선으로 빼야 한다."""
    body = SPAN_ONLY + "<hp:p>" + run(0, "경로 C:\\_temp 와 a\\_1") + "</hp:p>"
    _, md = run_main(monkeypatch, make_hwpx(tmp_path / "doc.hwpx", body=body))
    assert "<u>" not in md and "자동으로 켰" not in capsys.readouterr().out


@needs_underline
def test_header_failure_warning_carried_to_plain(tmp_path, monkeypatch, capsys):
    real = hwpx_tomd.convert

    def broken_header(filepath, *, underline=False, **kw):
        res = real(filepath, underline=underline, **kw)
        if underline:
            res.warnings.append("header.xml을 읽지 못해 밑줄을 표시하지 못했습니다: 합성 오류")
        return res

    monkeypatch.setattr(hwpx_tomd, "convert", broken_header)
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "doc.hwpx", body=SPAN_ONLY))
    assert code == 0 and "<u>" not in md
    assert "경고: header.xml을 읽지 못해" in capsys.readouterr().out


@needs_underline
def test_underline_conversion_error_keeps_plain(tmp_path, monkeypatch, capsys):
    real = hwpx_tomd.convert

    def ul_crash(filepath, *, underline=False, **kw):
        if underline:
            raise RuntimeError("합성 밑줄 오류")
        return real(filepath, **kw)

    monkeypatch.setattr(hwpx_tomd, "convert", ul_crash)
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "exam.hwpx"))
    assert code == 0 and "<u>" not in md
    assert "밑줄 보존 변환 실패" in capsys.readouterr().out


@needs_underline
def test_backslash_before_underline_span_still_counts_real_blank(tmp_path, monkeypatch, capsys):
    """원문 끝 `\\` + 밑줄 구간 첫 `_`는 plain에서만 `\\_`로 붙는다. 진짜 빈칸 1칸을 상쇄하면 안 된다."""
    body = (
        "<hp:p>" + run(0, "x\\") + run(1, "_y") + run(0, " 끝") + "</hp:p>"
        "<hp:p>" + run(0, "답: ") + run(1, " ") + run(0, " 쓰시오.") + "</hp:p>"
    )
    _, md = run_main(monkeypatch, make_hwpx(tmp_path / "doc.hwpx", body=body))
    assert "자동으로 켰" in capsys.readouterr().out and "<u>" in md


@needs_underline
def test_guard_warning_not_carried_to_plain(tmp_path, monkeypatch, capsys):
    real = hwpx_tomd.convert

    def lossy(filepath, *, underline=False, **kw):
        res = real(filepath, underline=underline, **kw)
        if underline:
            res.warnings.append("밑줄 표시가 렌더링 중 누락되었습니다: 밑줄 글자 2자. 확인하세요.")
        return res

    monkeypatch.setattr(hwpx_tomd, "convert", lossy)
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "doc.hwpx", body=SPAN_ONLY))
    assert code == 0 and "<u>" not in md
    assert "밑줄 표시가" not in capsys.readouterr().out
