"""gvision_parse 실행 계약: 모든 쪽이 빈 결과면 출력 파일 없이 1로 끝난다(SKILL.md Step 3).

인증·API 호출은 가짜로 바꿔 네트워크를 부르지 않는다.
"""
import sys

from _load import load


def _run(tmp_path, monkeypatch, text):
    g = load("parsers/gvision_parse.py", "gvision_parse")
    monkeypatch.setattr(g, "get_auth", lambda: ({"Authorization": "x"}, ""))
    monkeypatch.setattr(g, "annotate", lambda img, headers, suffix: {"fullTextAnnotation": {"text": text, "pages": []}})
    img = tmp_path / "scan.png"
    img.write_bytes(b"\x89PNG\r\n")
    monkeypatch.setattr(sys, "argv", ["gvision_parse.py", str(img)])
    return g.main(), tmp_path / "scan_gvision.md"


def test_all_pages_empty_is_failure(tmp_path, monkeypatch):
    code, out = _run(tmp_path, monkeypatch, "   ")
    assert code == 1
    assert not out.exists()


def test_text_is_success(tmp_path, monkeypatch):
    code, out = _run(tmp_path, monkeypatch, "hello")
    assert code == 0
    assert out.exists()
