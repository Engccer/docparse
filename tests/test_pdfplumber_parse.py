"""표 대조는 layout 모델 설치 여부와 무관하게 같은 괘선 검사를 유지한다."""
from types import SimpleNamespace
import subprocess
import sys

import pytest
from _load import load

P = load("parsers/pdfplumber_parse.py", "pdfplumber_compat")


def install_fake(monkeypatch, implementation, *, error=None):
    calls = []
    table = SimpleNamespace(bbox=(0, 0, 10, 10), extract=lambda: [["A", "B"]])

    class Page:
        cropbox = SimpleNamespace(x0=0, y1=100)
        mediabox = SimpleNamespace(x0=0, y1=100)

        def find_tables(self, **kwargs):
            calls.append(kwargs)
            if error:
                raise error
            return SimpleNamespace(tables=[table])

    class Document:
        def __enter__(self):
            return [Page()]

        def __exit__(self, *args):
            pass

    fake = SimpleNamespace(Page=Page, open=lambda _: Document())
    if implementation is not None:
        fake.table = SimpleNamespace(find_tables=implementation)
    monkeypatch.setitem(sys.modules, "fitz", fake)
    return calls


def test_supported_layout_option_is_explicitly_disabled(monkeypatch):
    def finder(page, strategy=None, use_layout=True):
        pass

    calls = install_fake(monkeypatch, finder)
    assert P._fitz_page_tables("fixture.pdf") == [[((0, 0, 10, 10), [["A", "B"]])]]
    assert calls == [{"strategy": "lines", "use_layout": False}]


@pytest.mark.parametrize("surface", ["old_signature", "missing_table_module"])
def test_legacy_surface_preserves_existing_call(monkeypatch, surface):
    def finder(page, strategy=None):
        pass

    calls = install_fake(monkeypatch, finder if surface == "old_signature" else None)
    P._fitz_page_tables("fixture.pdf", strategy="text")
    assert calls == [{"strategy": "text"}]


def test_internal_typeerror_is_not_retried_without_layout_option(monkeypatch):
    def finder(page, strategy=None, use_layout=True):
        pass

    calls = install_fake(monkeypatch, finder, error=TypeError("internal table failure"))
    with pytest.raises(TypeError, match="internal table failure"):
        P._fitz_page_tables("fixture.pdf")
    assert calls == [{"strategy": "lines", "use_layout": False}]


def test_real_grid_pdf_keeps_cells_with_installed_layout(tmp_path):
    pdf = pytest.importorskip("pymupdf")
    source = tmp_path / "grid.pdf"
    with pdf.open() as doc:
        page = doc.new_page(width=300, height=300)
        for x in (30, 130, 230):
            page.draw_line((x, 50), (x, 150))
        for y in (50, 100, 150):
            page.draw_line((30, y), (230, y))
        for point, value in [((40, 75), "A1"), ((140, 75), "B1"), ((40, 125), "A2"), ((140, 125), "B2")]:
            page.insert_text(point, value)
        doc.save(source)
    # PyMuPDF 1.x는 최초 import 시 stdout을 보관하므로 pytest 캡처 수명과 분리한다.
    code = """
import importlib.util
import sys
spec = importlib.util.spec_from_file_location('table_parser', sys.argv[1])
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
assert parser._fitz_page_tables(sys.argv[2]) == [[((30, 50, 230, 150), [['A1', 'B1'], ['A2', 'B2']])]]
"""
    run = subprocess.run([sys.executable, "-c", code, P.__file__, str(source)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
