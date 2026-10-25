"""ODL의 빈 출력은 실패하고, 유효한 Markdown은 변경 없이 저장한다."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from _load import load


def _run(tmp_path, monkeypatch, markdown):
    parser = load("parsers/opendataloader_parse.py", "opendataloader_parse")

    def convert(**kwargs):
        if markdown is not None:
            (Path(kwargs["output_dir"]) / "input.md").write_text(
                markdown, encoding="utf-8"
            )

    monkeypatch.setitem(sys.modules, "opendataloader_pdf", SimpleNamespace(convert=convert))
    monkeypatch.setattr(parser.shutil, "which", lambda name: "java")
    folder = tmp_path / "한글 경로"
    folder.mkdir()
    source = folder / "문서.pdf"
    source.write_bytes(b"%PDF-1.7\n")
    output = folder / "문서_opendataloader.md"
    output.write_text("이전 실행의 결과", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["opendataloader_parse.py", str(source)])
    return parser.main(), output


@pytest.mark.parametrize("markdown", [
    None,
    " \n\t",
    "| | |\n|---|---|\n| | |\n",
    "\n\n---\n<!-- Page 1 -->\n\n",
    "---\r\n<!-- Page 1 -->\r\n---\r\n<!-- Page 2 -->\r\n",
    "<!--\n Page 12 \n-->\n| | |\n|---|---|\n",
])
def test_empty_content_fails_without_stale_output(tmp_path, monkeypatch, markdown):
    code, output = _run(tmp_path, monkeypatch, markdown)
    assert code == 1
    assert not output.exists()


@pytest.mark.parametrize("markdown", [
    "<!-- Page 1 -->\n한국어 본문\n<!-- Page 2 -->\n",
    "<!-- Page 1 -->\n| 항목 | 값 |\n|---|---|\n| 수량 | 10 |\n",
    "<!-- Page 1 -->\n0\n",
    "<!-- Page 1 -->\nPage 1은 본문의 일부입니다.\n",
])
def test_nonempty_content_is_saved_unchanged(tmp_path, monkeypatch, markdown):
    code, output = _run(tmp_path, monkeypatch, markdown)
    assert code == 0
    assert output.read_text(encoding="utf-8") == markdown
