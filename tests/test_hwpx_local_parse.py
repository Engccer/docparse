"""hwpx_local_parse.py --underline: hwpx-tomd 0.5.0 밑줄 보존 연결(합성 HWPX, 네트워크 없음).

불변식: 플래그가 없으면 출력이 종전과 같고, 있으면 밑줄 구간은 <u>…</u>, 밑줄 빈칸은 공백 수만큼 \\_로 남는다.
설치된 엔진이 underline 인자를 모르면 밑줄 없이 변환하고 안내한다(출력·종료 코드 0 유지).
"""
import sys

import pytest

from _load import load
from hwpx_fixture import BLANK, SPAN, make_hwpx

hwpx_tomd = pytest.importorskip("hwpx_tomd")
P = load("parsers/hwpx_local_parse.py", "hwpx_local_parse")
needs_underline = pytest.mark.skipif(
    "underline" not in __import__("inspect").signature(hwpx_tomd.convert).parameters,
    reason="hwpx-tomd 0.5.0 미만",
)


def run_main(monkeypatch, path, *flags):
    monkeypatch.setattr(sys, "argv", ["hwpx_local_parse.py", str(path), *flags])
    code = P.main()
    out = path.with_name(path.stem + "_hwpxlocal.md")
    return code, out.read_text(encoding="utf-8") if out.exists() else None


def test_default_output_has_no_underline_markup(tmp_path, monkeypatch):
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "exam.hwpx"))
    assert code == 0
    assert "<u>" not in md and "\\_" not in md
    assert "I am to school." in md


@needs_underline
def test_underline_flag_preserves_span_and_blank(tmp_path, monkeypatch, capsys):
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "exam.hwpx"), "--underline")
    assert code == 0
    assert f"I am {BLANK} to school." in md
    assert f"2. (A) {SPAN} 중 어법상 틀린 것은?" in md
    assert "밑줄 표시가" not in capsys.readouterr().out  # 보존 가드 통과


def test_old_engine_falls_back_with_notice(tmp_path, monkeypatch, capsys):
    real = hwpx_tomd.convert

    def old_convert(filepath, *, cell_br=False, merge_fill=False):  # 0.4.x 시그니처
        return real(filepath, cell_br=cell_br, merge_fill=merge_fill)

    monkeypatch.setattr(hwpx_tomd, "convert", old_convert)
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "exam.hwpx"), "--underline")
    assert code == 0
    assert "<u>" not in md
    assert "hwpx-tomd>=0.5.0" in capsys.readouterr().out


@needs_underline
def test_underline_guard_warning_keeps_output(tmp_path, monkeypatch, capsys):
    real = hwpx_tomd.convert

    def lossy(filepath, **kw):
        res = real(filepath, **kw)
        res.warnings.append("밑줄 표시가 렌더링 중 누락되었습니다: 밑줄 빈칸 6칸. 확인하세요.")
        return res

    monkeypatch.setattr(hwpx_tomd, "convert", lossy)
    code, md = run_main(monkeypatch, make_hwpx(tmp_path / "exam.hwpx"), "--underline")
    assert code == 0 and md
    assert "경고: 밑줄 표시가" in capsys.readouterr().out
