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


def _grid_pdf(path, *, dots=False, rotation=0, merged=False):
    """괘선 표 PDF. dots: 쪽 전체에 채움만 있는 작은 장식 사각형(슬라이드 배경 무늬).

    merged: 3x3 표에서 왼쪽 칸이 1~2행을 세로로, 오른쪽 위 칸이 2~3열을 가로로 병합된다.
    """
    pdf = pytest.importorskip("pymupdf")
    with pdf.open() as doc:
        page = doc.new_page(width=400, height=600)
        if dots:
            for gx in range(16):
                for gy in range(24):
                    x, y = 6 + gx * 24, 6 + gy * 24
                    page.draw_rect((x, y, x + 9, y + 9), color=None, fill=(0.87, 0.87, 0.87))
        if merged:
            for x0, y0, x1, y1 in [(30, 50, 330, 50), (30, 200, 330, 200), (30, 150, 330, 150),
                                   (130, 100, 330, 100), (30, 50, 30, 200), (330, 50, 330, 200),
                                   (130, 50, 130, 200), (230, 100, 230, 200)]:
                page.draw_line((x0, y0), (x1, y1))
            cells = [((40, 105), "No"), ((140, 80), "Group"), ((140, 130), "B2"), ((240, 130), "C2"),
                     ((40, 180), "A3"), ((140, 180), "B3"), ((240, 180), "C3")]
        else:
            for x in (30, 130, 230):
                page.draw_line((x, 50), (x, 450))
            for y in (50, 250, 450):
                page.draw_line((30, y), (230, y))
            cells = [((40, 150), "A1"), ((140, 150), "B1"), ((40, 350), "A2"), ((140, 350), "B2")]
        for point, value in cells:
            page.insert_text(point, value)
        if rotation:
            page.set_rotation(rotation)
        doc.save(path)
    return path


def _run(source, *extra):
    """파서를 별도 프로세스로 돌린다(PyMuPDF의 stdout 보관을 pytest 캡처 수명과 분리)."""
    return subprocess.run([sys.executable, P.__file__, str(source), *extra],
                          capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)


def test_decorative_small_shapes_are_excluded_on_retry(tmp_path):
    """작은 장식 도형이 격자로 잡혀 실패하면, 그 도형만 뺀 설정으로 한 번 더 시도해 같은 검증을 통과시킨다."""
    run = _run(_grid_pdf(tmp_path / "dots.pdf", dots=True))
    assert run.returncode == 0, run.stdout + run.stderr
    assert "작은 채움 도형" in run.stdout
    text = (tmp_path / "dots_pdfplumber.md").read_text(encoding="utf-8")
    assert "| A1 | B1 |" in text and "| A2 | B2 |" in text


def test_retry_keeps_rulings_drawn_cell_by_cell(tmp_path):
    """칸마다 끊어 그린 짧은 괘선(13pt)은 재시도에서도 남는다. 빼면 두 엔진이 같이 열을 합쳐 틀린 표가 통과한다."""
    pdf = pytest.importorskip("pymupdf")
    path = tmp_path / "segments.pdf"
    with pdf.open() as doc:
        page = doc.new_page(width=400, height=600)
        for gx in range(16):
            for gy in range(24):
                x, y = 6 + gx * 24, 6 + gy * 24
                page.draw_rect((x, y, x + 9, y + 9), color=None, fill=(0.87, 0.87, 0.87))
        xs, ys = [30, 110, 190, 270], [100 + 13 * i for i in range(5)]
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for x in (xs[0], xs[1], xs[-1]):
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y0, y1 in zip(ys, ys[1:]):
            page.draw_line((xs[2], y0), (xs[2], y1))
        for r in range(4):
            for c in range(3):
                page.insert_text((xs[c] + 5, ys[r] + 10), f"R{r}C{c}", fontsize=8)
        doc.save(path)
    run = _run(path)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "| R0C0 | R0C1 | R0C2 |" in (tmp_path / "segments_pdfplumber.md").read_text(encoding="utf-8")


def _dashed_divider_pdf(path, dots, gap=2, sparse=False, double=False):
    """3열 표. 2·3열 사이 칸막이는 선이 아니라 채움만 있는 4x8pt 사각형을 gap 간격으로 늘어놓은 굵은 점선이다.

    sparse면 행마다 2·3열 가운데 한쪽에만 값을 둔다. double이면 점선을 두 줄로 나란히 그린다."""
    pdf = pytest.importorskip("pymupdf")
    with pdf.open() as doc:
        page = doc.new_page(width=400, height=600)
        if dots:
            for gx in range(16):
                for gy in range(24):
                    x, y = 6 + gx * 24, 6 + gy * 24
                    page.draw_rect((x, y, x + 9, y + 9), color=None, fill=(0.87, 0.87, 0.87))
        xs, ys = [30, 110, 190, 270], [100 + 20 * i for i in range(5)]
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for x in (xs[0], xs[1], xs[-1]):
            page.draw_line((x, ys[0]), (x, ys[-1]))
        y = ys[0]
        while y < ys[-1]:
            for dx in ((-5, 5) if double else (0,)):
                page.draw_rect((xs[2] + dx - 2, y, xs[2] + dx + 2, min(y + 8, ys[-1])), color=None, fill=(0, 0, 0))
            y += 8 + gap
        for r in range(4):
            for c in range(3):
                if sparse and c == 1 + (r % 2):
                    continue
                page.insert_text((xs[c] + 8, ys[r] + 14), f"R{r}C{c}", fontsize=8)
        doc.save(path)
    return path


def test_only_two_dimensional_patterns_are_decor():
    """2차원 무늬(체크무늬)만 장식으로 뺀다. 한 방향으로만 이어진 줄과 외톨이 도형은 남긴다."""
    checker = [((x * 6.6, y * 6.6, x * 6.6 + 6.6, y * 6.6 + 6.6), True, False)
               for x in range(4) for y in range(6) if (x + y) % 2 == 0]
    assert P._decor_boxes(checker) == set(range(len(checker)))
    runs = []
    for gap in (2, 4, 6, 10):                                              # 세로·가로 점선, 간격별
        runs += [((100 + 40 * gap, (8 + gap) * k, 104 + 40 * gap, (8 + gap) * k + 8), True, False) for k in range(5)]
        runs += [((500 + (8 + gap) * k, 300 + 40 * gap, 508 + (8 + gap) * k, 304 + 40 * gap), True, False)
                 for k in range(5)]
    lone = [((300, 900, 306, 906), True, False)]
    assert P._decor_boxes(checker + runs + lone) == set(range(len(checker)))
    beside = [((13.2, 40, 17.2, 46.6), True, False)]                       # 무늬 줄에 높이만 맞춘 다른 크기 도형
    assert P._decor_boxes(checker + beside) == set(range(len(checker)))
    stroked = [(box, True, True) for box, _, _ in checker]                 # 테두리가 있으면 무늬여도 남긴다
    assert P._decor_boxes(stroked) == set()


@pytest.mark.parametrize("gap", [2, 4, 6])
@pytest.mark.parametrize("sparse", [False, True])
def test_retry_never_removes_a_dashed_divider(tmp_path, gap, sparse):
    """굵은 점선 칸막이는 간격과 무관하게 재시도에서 남는다. 그래서 무늬가 깔린 쪽의 결과는
    무늬가 없는 같은 쪽의 결과와 같다(둘 다 실패하거나, 같은 표를 낸다)."""
    pdfplumber = pytest.importorskip("pdfplumber")
    with_dots = _dashed_divider_pdf(tmp_path / "dots.pdf", dots=True, gap=gap, sparse=sparse)
    plain = _dashed_divider_pdf(tmp_path / "plain.pdf", dots=False, gap=gap, sparse=sparse)
    with pdfplumber.open(with_dots) as doc:
        removed = [box for group in P._without_decor(doc.pages[0])[1] for box in group]
        assert removed and all(box[2] - box[0] > 5 for box in removed)   # 9pt 무늬만 빠지고 4pt 폭 대시는 남았다
    a, b = _run(with_dots), _run(plain)
    assert a.returncode == b.returncode, a.stdout + b.stdout
    if a.returncode == 0:
        assert ((tmp_path / "dots_pdfplumber.md").read_text(encoding="utf-8")
                == (tmp_path / "plain_pdfplumber.md").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sparse", [False, True])
def test_retry_is_rejected_when_a_removed_pattern_sits_inside_the_table(tmp_path, sparse):
    """두 줄로 나란히 그린 점선 칸막이는 2차원 무늬에 들어 재시도에서 빠진다. 그러면 두 엔진이 똑같이
    열을 합치므로, 뺀 무늬가 주로 표 안에 있으면 재시도를 버린다(칸이 듬성해도, 출력 없음)."""
    run = _run(_dashed_divider_pdf(tmp_path / "dashed.pdf", dots=True, double=True, sparse=sparse))
    assert run.returncode == 1, run.stdout + run.stderr
    assert "주로 표 안" in run.stdout
    assert ("낱말 사이" in run.stdout) == (not sparse)
    assert not (tmp_path / "dashed_pdfplumber.md").exists()


def test_decor_patterns_are_judged_by_where_they_lie():
    """무늬는 이웃 관계로 이어진 덩어리 단위로 본다. 절반 넘게 표 안에 있는 무늬만 표의 일부로 친다."""
    margin = [(x * 6.6, y * 6.6, x * 6.6 + 6.6, y * 6.6 + 6.6) for x in range(4) for y in range(20) if (x + y) % 2 == 0]
    double = [(200 + dx, 10 * k + 40, 204 + dx, 10 * k + 48) for dx in (0, 10) for k in range(6)]
    groups = P._lattice(margin + double)   # 체크무늬는 엇갈린 두 덩어리로 잡힌다
    assert sorted(map(len, groups)) == [len(double), len(margin) // 2, len(margin) // 2]
    boxes = [[(margin + double)[i] for i in group] for group in groups]
    table = SimpleNamespace(bbox=(20, 30, 300, 110))       # 여백 무늬는 오른쪽 한 줄만 걸친다
    assert P._decor_inside_tables([table], boxes) == 1
    assert P._decor_inside_tables([SimpleNamespace(bbox=(20, 30, 150, 110))], boxes) == 0
    assert P._decor_inside_tables([], boxes) == 0


def test_decor_beside_words_is_not_between_them():
    """칸 가장자리에 걸친 여백 무늬(낱말들 옆으로 비켜난 도형)는 칸막이로 세지 않는다."""
    words = [{"text": "PT", "x0": 20, "x1": 40, "top": 10, "bottom": 20},
             {"text": "Plant", "x0": 15, "x1": 50, "top": 30, "bottom": 40}]
    page = SimpleNamespace(extract_words=lambda: words)
    table = SimpleNamespace(bbox=(0, 0, 100, 50), rows=[SimpleNamespace(cells=[(0, 0, 100, 50)])])
    count = lambda box: P._decor_between_words(page, [table], [box])
    assert count((80, 22, 86, 28)) == 0      # 두 줄 사이 높이지만 낱말들 오른쪽으로 비켜나 있다
    assert count((25, 22, 31, 28)) == 1      # 위아래 낱말 사이
    words.append({"text": "X", "x0": 70, "x1": 76, "top": 10, "bottom": 20})
    assert count((52, 12, 58, 18)) == 1      # 같은 줄의 좌우 낱말 사이
    assert count((200, 12, 206, 18)) == 0    # 표 밖
    assert count((44, 12, 72, 18)) == 0      # 낱말에 겹친 도형(글자 뒤에 깔린 무늬)


def test_boundary_words_are_found_from_a_real_page(tmp_path):
    """행 경계선을 가로지르는 낱말만 걸친 자리로 잡는다(경계선 = 아래 행의 윗변)."""
    pdf = pytest.importorskip("pymupdf")
    pdfplumber = pytest.importorskip("pdfplumber")
    path = tmp_path / "straddle.pdf"
    with pdf.open() as doc:
        page = doc.new_page(width=400, height=600)
        for x in (30, 130, 230):
            page.draw_line((x, 50), (x, 350))
        for y in (50, 150, 250, 350):
            page.draw_line((30, y), (230, y))
        page.insert_text((40, 100), "Inside")          # 첫 행 한가운데
        page.insert_text((140, 154), "Across")         # 첫·둘째 행 경계선(y=150)에 걸친다
        page.insert_text((40, 300), "Below")
        doc.save(path)
    with pdfplumber.open(path) as doc:
        page = doc.pages[0]
        assert P._boundary_words(page, page.find_tables()) == {(0, 0, 1)}


def test_decor_rule_spares_thin_and_stroked_shapes():
    assert P._is_decor(6, 6.6, True, False)
    assert not P._is_decor(0.5, 13, True, False)   # 채운 사각형으로 그린 가는 괘선
    assert not P._is_decor(8, 8, True, True)       # 테두리가 있는 도형(체크 상자 등)
    assert not P._is_decor(8, 8, False, True)
    assert not P._is_decor(20, 6, True, False)


def test_plain_grid_passes_without_retry(tmp_path):
    run = _run(_grid_pdf(tmp_path / "plain.pdf"))
    assert run.returncode == 0, run.stdout + run.stderr
    assert "작은 채움 도형" not in run.stdout and "회전" not in run.stdout


def test_rotated_page_is_normalised_before_extraction(tmp_path):
    """/Rotate가 걸린 쪽은 두 엔진의 좌표계가 달라지므로 회전을 푼 사본으로 추출한다."""
    source = _grid_pdf(tmp_path / "rot.pdf", rotation=90)
    before = source.read_bytes()
    run = _run(source)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "회전" in run.stdout
    assert source.read_bytes() == before
    # 화면에 보이는 방향(시계 방향 90도)대로 읽힌다
    assert (tmp_path / "rot_pdfplumber.md").read_text(encoding="utf-8") == "| A2 | A1 |\n| --- | --- |\n| B2 | B1 |\n"


def test_merged_cells_keep_their_span_as_html(tmp_path):
    """병합 칸은 범위를 되찾아 rowspan·colspan이 있는 HTML 표로 내보낸다(종전에는 실패 처리)."""
    run = _run(_grid_pdf(tmp_path / "merged.pdf", merged=True))
    assert run.returncode == 0, run.stdout + run.stderr
    assert "병합 칸 2개" in run.stdout
    text = (tmp_path / "merged_pdfplumber.md").read_text(encoding="utf-8")
    assert '<td rowspan="2">No</td><td colspan="2">Group</td>' in text
    assert "<tr><td>B2</td><td>C2</td></tr>" in text
    assert "<tr><td>A3</td><td>B3</td><td>C3</td></tr>" in text


def test_text_strategy_still_rejects_merged_cells(tmp_path):
    """괘선이 없는 text 전략은 병합 범위를 되찾을 근거가 없으므로 HTML 병합 표를 내지 않는다."""
    _run(_grid_pdf(tmp_path / "m.pdf", merged=True), "--strategy", "text")
    out = tmp_path / "m_pdfplumber.md"
    assert not out.exists() or "<table>" not in out.read_text(encoding="utf-8")


def test_unexplained_empty_slot_is_not_a_span():
    """None 자리가 병합 칸 하나로 설명되지 않으면 범위를 지어내지 않는다."""
    def table(rows):
        return SimpleNamespace(rows=[SimpleNamespace(cells=c, bbox=(0, c_top, 30, c_top + 10))
                                     for c_top, c in rows])
    ok = table([(0, [(0, 0, 10, 20), (10, 0, 30, 10), None]),
                (10, [None, (10, 10, 20, 20), (20, 10, 30, 20)])])
    assert P.table_spans(ok) == {(0, 0): (2, 1), (0, 1): (1, 2)}
    hole = table([(0, [(0, 0, 10, 10), (10, 0, 20, 10), (20, 0, 30, 10)]),
                  (10, [None, (10, 10, 20, 20), (20, 10, 30, 20)])])
    assert P.table_spans(hole) is None


def _cross(monkeypatch, ours, theirs, touching=None):
    monkeypatch.setattr(P, "_fitz_page_tables", lambda *a, **k: [[((0, 0, 10, 10), theirs)]])
    return P.crosscheck_with_fitz("x.pdf", [[((0, 0, 10, 10), ours)]],
                                  boundary_words=None if touching is None else [touching])


def test_text_on_a_cell_border_is_reported_not_failed(monkeypatch):
    """글자가 위아래 칸 경계에 걸쳐 두 구현의 배정만 갈리면 불일치가 아니라 걸친 자리로 알린다."""
    ours = [["No", ""], [None, "Customer"], ["1", "ACME"]]
    checked, problems, straddles = _cross(monkeypatch, ours, [["No", "Customer"], [None, ""], ["1", "ACME"]], {(0, 0, 1)})
    assert (checked, problems) == (6, []) and len(straddles) == 1 and "Customer" in straddles[0]
    # 그 경계선에 닿은 낱말이 없으면(좌표 근거 없음) 종전대로 불일치다
    assert len(_cross(monkeypatch, ours, [["No", "Customer"], [None, ""], ["1", "ACME"]], set())[1]) == 2
    assert len(_cross(monkeypatch, ours, [["No", "Customer"], [None, ""], ["1", "ACME"]])[1]) == 2
    # 값 자체가 다르면 불일치다
    assert len(_cross(monkeypatch, ours, [["No", "Custom"], [None, ""], ["1", "ACME"]], {(0, 0, 1)})[1]) == 2
    # 빈 칸이 아닌 두 칸이 서로 바뀐 것은 걸침이 아니다
    assert len(_cross(monkeypatch, ours, [["No", ""], [None, "Customer"], ["ACME", "1"]], {(0, 0, 1), (0, 1, 1)})[1]) == 2


def test_a_cell_is_paired_as_straddle_only_once(monkeypatch):
    """내용 개수가 다른 열(한쪽 1칸, 다른 쪽 2칸)은 가운데 칸을 두 번 짝지어 통과시키지 않는다."""
    everywhere = {(0, 0, 0), (0, 1, 0)}
    checked, problems, straddles = _cross(monkeypatch, [[""], ["0"], [""]], [["0"], [""], ["0"]], everywhere)
    assert len(straddles) == 1 and len(problems) == 1


def test_merged_slot_must_match_on_both_sides(monkeypatch):
    """한 엔진만 병합으로 본 자리는 값이 비어 있어도 불일치다."""
    assert len(_cross(monkeypatch, [["A", ""], ["B", "C"]], [["A", None], ["B", "C"]])[1]) == 1


def _divider_pdf(path, draw, sparse=False, dots=False):
    """3열 괘선 표. 2·3열 사이 칸막이는 draw(page, x, top, bottom)가 그린다. sparse면 행마다 2·3열 가운데 한쪽에만 값."""
    pdf = pytest.importorskip("pymupdf")
    xs, ys = [30, 110, 190, 270], [100 + 20 * i for i in range(5)]
    with pdf.open() as doc:
        page = doc.new_page(width=400, height=600)
        if dots:
            for gx in range(16):
                for gy in range(24):
                    x, y = 6 + gx * 24, 6 + gy * 24
                    page.draw_rect((x, y, x + 9, y + 9), color=None, fill=(0.87, 0.87, 0.87))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for x in (xs[0], xs[1], xs[-1]):
            page.draw_line((x, ys[0]), (x, ys[-1]))
        draw(page, xs[2], ys[0], ys[-1])
        for r in range(4):
            for c in range(3):
                if sparse and c == 1 + (r % 2):
                    continue
                page.insert_text((xs[c] + 8, ys[r] + 14), f"R{r}C{c}", fontsize=8)
        doc.save(path)
    return path


def _dashes(width, height, gap, segments=False):
    """세로 점선: 채움만 있는 width x height 사각형(segments면 길이 height인 선분)을 gap 간격으로."""
    def draw(page, x, top, bottom):
        y = top + gap / 2
        while y < bottom:
            end = min(y + height, bottom)
            if segments:
                page.draw_line((x, y), (x, end))
            else:
                page.draw_rect((x - width / 2, y, x + width / 2, end), color=None, fill=(0, 0, 0))
            y += height + gap
    return draw


PLAIN_3COL = ("| R0C0 | R0C1 | R0C2 |\n| --- | --- | --- |\n| R1C0 | R1C1 | R1C2 |\n"
              "| R2C0 | R2C1 | R2C2 |\n| R3C0 | R3C1 | R3C2 |\n")


@pytest.mark.parametrize("draw", [
    lambda page, x, top, bottom: page.draw_rect((x - 2, top, x + 2, bottom), color=None, fill=(0, 0, 0)),
    _dashes(4, 8, 2),
], ids=["thick_rule", "dash_ends"])
def test_empty_slivers_from_thick_rules_and_dash_ends_are_folded(tmp_path, draw):
    """굵은 괘선의 양쪽 가장자리나 점선 대시의 끝이 만든 내용 없는 얇은 열·행은 접혀, 값과 칸 배정이 같은 3열 표가 된다."""
    run = _run(_divider_pdf(tmp_path / "t.pdf", draw))
    assert run.returncode == 0, run.stdout + run.stderr
    assert (tmp_path / "t_pdfplumber.md").read_text(encoding="utf-8") == PLAIN_3COL


def _table(xs, ys, cells):
    """xs·ys: 열·행 경계선. cells: {(r, c): (rowspan, colspan)} 시작 칸만. 나머지 자리는 None."""
    rows = []
    for r in range(len(ys) - 1):
        row = [None] * (len(xs) - 1)
        for (r0, c0), (rs, cs) in cells.items():
            if r0 == r:
                row[c0] = (xs[c0], ys[r0], xs[c0 + cs], ys[r0 + rs])
        top = min(cell[1] for cell in row if cell)
        rows.append(SimpleNamespace(cells=row, bbox=(xs[0], top, xs[-1], ys[r + 1])))
    return SimpleNamespace(rows=rows, bbox=(xs[0], ys[0], xs[-1], ys[-1]))


def test_fold_shrinks_spans_and_keeps_values():
    """얇은 빈 열(2pt)이 병합 칸을 가로지르면 colspan이 줄고, 덮인 자리뿐인 행은 rowspan을 줄이며 사라진다."""
    xs, ys = [0, 40, 80, 82, 120], [0, 20, 22, 42, 62]
    cells = {(0, 0): (3, 1), (0, 1): (1, 3), (1, 1): (1, 1), (1, 2): (1, 1), (1, 3): (1, 1),
             (2, 1): (1, 1), (2, 2): (1, 1), (2, 3): (1, 1), (3, 0): (1, 1), (3, 1): (1, 1),
             (3, 2): (1, 1), (3, 3): (1, 1)}
    grid = [["No", "Group", None, None], [None, "", "", ""], [None, "B", "", "C"], ["1", "x", "", ""]]
    spans = {(0, 0): (3, 1), (0, 1): (1, 3)}
    folded = P._fold_empty(_table(xs, ys, cells), grid, spans, 8)
    assert folded == ([["No", "Group", None], [None, "B", "C"], ["1", "x", ""]], {(0, 0): (2, 1), (0, 1): (1, 2)})
    # 8pt보다 두꺼운 빈 행·열(일부러 비운 양식 칸)은 남는다
    xs, ys = [0, 40, 80, 100], [0, 20, 40, 60]
    plain = {(r, c): (1, 1) for r in range(3) for c in range(3)}
    grid = [["A", "B", ""], ["", "", ""], ["C", "D", ""]]
    assert P._fold_empty(_table(xs, ys, plain), grid, None, 8) == (grid, None)


def test_wide_empty_rows_and_columns_are_kept(tmp_path):
    """일부러 비운 빈 행(20pt)과 빈 열(40pt)은 접지 않는다."""
    pdf = pytest.importorskip("pymupdf")
    path = tmp_path / "form.pdf"
    xs, ys = [30, 110, 190, 230], [100, 120, 140, 160]
    with pdf.open() as doc:
        page = doc.new_page(width=400, height=600)
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for r, c, value in [(0, 0, "Name"), (0, 1, "Sign"), (2, 0, "Kim"), (2, 1, "Lee")]:
            page.insert_text((xs[c] + 8, ys[r] + 14), value, fontsize=8)
        doc.save(path)
    run = _run(path)
    assert run.returncode == 0, run.stdout + run.stderr
    assert (tmp_path / "form_pdfplumber.md").read_text(encoding="utf-8") == (
        "| Name | Sign |  |\n| --- | --- | --- |\n|  |  |  |\n| Kim | Lee |  |\n")


@pytest.mark.parametrize("sparse", [False, True])
@pytest.mark.parametrize("draw", [_dashes(1, 4, 6), _dashes(2, 8, 10), _dashes(4, 8, 6), _dashes(4, 8, 10),
                                  _dashes(1, 4, 6, segments=True)],
                         ids=["1x4_gap6", "2x8_gap10", "4x8_gap6", "4x8_gap10", "segments"])
def test_dotted_divider_inside_a_cell_is_rejected(tmp_path, draw, sparse):
    """3pt 넘는 간격의 세로 점선은 두 엔진 모두 선으로 보지 못해 두 열을 한 칸으로 합친다. 그 점선 양쪽에
    낱말이 있으면(칸이 듬성해 행마다 한쪽에만 있어도) 출력하지 않는다."""
    run = _run(_divider_pdf(tmp_path / "d.pdf", draw, sparse=sparse))
    assert run.returncode == 1, run.stdout + run.stderr
    assert "점선" in run.stdout
    assert not (tmp_path / "d_pdfplumber.md").exists()


def _cell_shapes_pdf(path, kind):
    """2열 괘선 표의 칸 안에 칸막이가 아닌 작은 채움 도형을 둔다."""
    pdf = pytest.importorskip("pymupdf")
    xs, ys = [30, 150, 270], [100, 160, 220, 240]
    with pdf.open() as doc:
        page = doc.new_page(width=400, height=600)
        if kind == "band":                                   # 머리 행 뒤에 깔린 색 띠
            page.draw_rect((xs[0], ys[2], xs[-1], ys[3]), color=None, fill=(0.8, 0.9, 1))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for r in range(2):
            for c in range(2):
                for k, word in enumerate(("Apple", "Pear", "Plum")):
                    y = ys[r] + 14 + 14 * k
                    if kind in ("bullets", "boxes"):               # 글머리 기호, 낱말 앞 체크 상자
                        x = xs[c] + 6
                        page.draw_rect((x, y - 5, x + 5, y), color=None, fill=(0, 0, 0))
                        page.insert_text((x + 9, y), f"{word}{r}{c}", fontsize=8)
                    else:
                        page.insert_text((xs[c] + 8, y), f"{word}{r}{c}", fontsize=8)
        page.insert_text((xs[0] + 8, ys[2] + 14), "Total", fontsize=8)
        doc.save(path)
    return path


@pytest.mark.parametrize("kind", ["bullets", "boxes", "band"])
def test_small_shapes_that_do_not_divide_a_cell_still_pass(tmp_path, kind):
    """낱말 앞에 세로로 늘어선 글머리 기호·체크 상자와 넓은 색 띠는 칸막이가 아니므로 통과한다."""
    run = _run(_cell_shapes_pdf(tmp_path / "s.pdf", kind))
    assert run.returncode == 0, run.stdout + run.stderr
    assert "점선" not in run.stdout


@pytest.mark.parametrize("gap", [1, 2, 3])
def test_retry_is_rejected_when_a_joined_dash_run_merges_into_page_decor(tmp_path, gap):
    """장식 무늬와 크기가 같은 대시를 무늬 열 옆 3pt에 3pt 이하 간격으로 이은 칸막이는 무늬 덩어리에 합쳐져
    재시도에서 빠진다. 무늬 덩어리는 대부분 표 밖이어도, 이어 붙은 대시 줄이 표 안에 있으면 재시도를 버린다."""
    def draw(page, x, top, bottom):
        y = 102
        while y < bottom:
            page.draw_rect((186, y, 195, y + 9), color=None, fill=(0, 0, 0))
            y += 9 + gap
    run = _run(_divider_pdf(tmp_path / "j.pdf", draw, sparse=True, dots=True))
    assert run.returncode == 1, run.stdout + run.stderr
    assert not (tmp_path / "j_pdfplumber.md").exists()


def test_word_break_difference_is_not_a_mismatch(monkeypatch):
    """낱말을 끊는 자리만 다른 값은 같은 내용이다. 글자 순서가 바뀐 값은 아니다."""
    ours = [["NORTH PLANT_UNIT PHASE"]]
    assert _cross(monkeypatch, ours, [["UNIT\nNORTH PLANT\nPHASE\n_"]]) == (1, [], [])
    assert len(_cross(monkeypatch, ours, [["NORTH PLANT_UNIT PHASE 2"]])[1]) == 1
    # 숫자가 든 낱말은 끊는 자리가 달라도 같다고 보지 않는다
    for a, b in (("PHASE", "PHAES"), ("1,250", "1,520"), ("10 25", "15 20"), ("2019", "2091"),
                 ("51", "5 1"), ("1/2", "2 / 1"), ("A105_B", "A105 _ B")):
        assert len(_cross(monkeypatch, [[a]], [[b]])[1]) == 1, (a, b)
