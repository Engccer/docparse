"""hwpx_local_parse.py 밑줄 보존: hwpx-tomd 0.5.0 연결(합성 HWPX, 네트워크 없음).

불변식: 엔진이 밑줄 빈칸(\\_)을 하나라도 내면 밑줄 보존을 자동으로 켜고, 장식 밑줄만 있는 문서는 출력이
종전과 같다. --underline은 빈칸이 없어도 켠다. 설치된 엔진이 underline 인자를 모르면 밑줄 없이 변환하고
안내한다(출력·종료 코드 0 유지).
"""
import inspect
import sys

import pytest

from _load import load
from hwpx_fixture import BLANK, SPAN, SPAN_ONLY, make_hwpx

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
