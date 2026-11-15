"""md_to_reading: 파서 출력(마크다운·HTML 표)을 칸별 대조용 판독 JSON으로 바꾼다."""
import json
import subprocess
import sys

from _load import ROOT, load

m = load("scripts/md_to_reading.py", "md_to_reading")

PIPE = """<!-- Page 1/1 -->

| SIZE | Out side Diam. | Length Through Hub |   |
| --- | --- | --- | --- |
|   |   | Welding Neck | Lap Joint |
|   | O | T1 | T3 |
| 1/2 | 90 | 46 | 16 |
| 3/4 | 100 | 51 | 16 |
| 1 | 110 | 54 | 17 |
"""

HTML = """<table>
<tr><th rowspan="2">SIZE</th><th colspan="2">BORE</th></tr>
<tr><th>B1</th><th>B2</th></tr>
<tr><td>14</td><td rowspan="2">To be specified</td><td>359.2</td></tr>
<tr><td>16</td><td>410.5</td></tr>
</table>"""


def test_pipe_table_splits_header_and_body():
    grid = m.to_grid(m.largest_table(PIPE))
    assert grid["columns"] == 4
    assert grid["rows"] == [["1/2", "90", "46", "16"], ["3/4", "100", "51", "16"], ["1", "110", "54", "17"]]
    assert grid["header"][0] == "SIZE"
    assert grid["header"][2] == "Length Through Hub / Welding Neck / T1"


def test_html_spans_are_expanded():
    rows = m.largest_table(HTML)
    assert rows[0] == ["SIZE", "BORE", "BORE"]
    assert rows[2] == ["14", "To be specified", "359.2"]
    assert rows[3] == ["16", "To be specified", "410.5"]
    grid = m.to_grid(rows)
    # 본문의 병합 칸은 첫 칸에만 값을 둔다(서브에이전트 판독의 표기와 같게)
    assert grid["rows"] == [["14", "To be specified", "359.2"], ["16", "", "410.5"]]
    assert grid["header"] == ["SIZE", "BORE / B1", "BORE / B2"]
    assert all(type(c) is str for r in grid["rows"] for c in r)


def test_largest_table_wins_and_br_becomes_space():
    text = "| a | b |\n| - | - |\n| 1 | 2 |\n\n" + PIPE.replace("Out side Diam.", "Out side<br/>Diam.")
    rows = m.largest_table(text)
    assert rows[0][1] == "Out side Diam."
    assert len(rows) == 6


def test_short_rows_are_padded_and_noted():
    grid = m.to_grid([["A", "B", "C"], ["1", "2", "3"], ["4", "5"]])
    assert grid["rows"][1] == ["4", "5", ""]
    assert "폭" in grid["notes"]


def test_text_table_body_starts_at_numeric_first_cell():
    rows = [["", "GROUP 1 MATERIALS", "PRODUCT FORMS"], ["Material Group No.", "Steel", "Forgings"],
            ["1.1", "C-Si", "A105"], ["", "C-Mn-Si", "A350-LF2"]]
    grid = m.to_grid(rows)
    assert grid["rows"] == [["1.1", "C-Si", "A105"], ["", "C-Mn-Si", "A350-LF2"]]


def test_all_text_table_keeps_first_row_as_header():
    grid = m.to_grid([["이름", "비고"], ["가", "나"], ["다", "라"]])
    assert grid["header"] == ["이름", "비고"]
    assert grid["rows"] == [["가", "나"], ["다", "라"]]


def test_percent_and_parenthesised_numbers_are_body():
    rows = [["구분", "비율", "금액"], ["Alpha", "12%", "(1,200)"], ["Beta", "±0.5", "△3"]]
    assert m.to_grid(rows)["rows"] == rows[1:]


def test_column_number_row_stays_in_header():
    rows = [["(1)", "(2)", "(3)"], ["Ring Number", "Outside Diameter", "Width"], ["R-20", "85.34", "15.75"]]
    grid = m.to_grid(rows)
    assert grid["rows"] == [["R-20", "85.34", "15.75"]]
    assert grid["header"][0] == "(1) / Ring Number"


def test_no_table_returns_none():
    assert m.largest_table("표가 없는 본문입니다.") is None


def test_grid_id_from_filename():
    assert m.grid_id("p004.g01.overview_upstage.md") == "p004.g01"
    assert m.grid_id("notes.md") is None


def _run(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "md_to_reading.py"), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)


def test_cli_folder_with_suffix(tmp_path):
    (tmp_path / "p004.g00.overview_upstage.md").write_text(PIPE, encoding="utf-8")
    (tmp_path / "p004.g01.overview_upstage.md").write_text(HTML, encoding="utf-8")
    (tmp_path / "p004.g00.overview_mistral.md").write_text("| x | y |\n| - | - |\n| 9 | 9 |\n", encoding="utf-8")
    (tmp_path / "p005.g00.overview_upstage.md").write_text("표 없음", encoding="utf-8")
    out = tmp_path / "upstage.json"
    r = _run(tmp_path, "--suffix", "_upstage", "--out", out)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert sorted(data["grids"]) == ["p004.g00", "p004.g01"]
    assert data["grids"]["p004.g00"]["rows"][0] == ["1/2", "90", "46", "16"]
    assert "p005.g00" in r.stdout and "표 없음" in r.stdout


def test_cli_no_match_is_error(tmp_path):
    r = _run(tmp_path, "--suffix", "_upstage", "--out", tmp_path / "x.json")
    assert r.returncode == 1
    assert not (tmp_path / "x.json").exists()


def test_cli_duplicate_grid_id_is_error_and_clears_old_output(tmp_path):
    """--suffix 없이 여러 파서 출력이 섞이면 조용히 하나를 고르지 않고 실패한다."""
    (tmp_path / "p004.g00.overview_upstage.md").write_text(PIPE, encoding="utf-8")
    (tmp_path / "p004.g00.overview_gemini.md").write_text(PIPE, encoding="utf-8")
    out = tmp_path / "all.json"
    out.write_text("{}", encoding="utf-8")
    r = _run(tmp_path, "--out", out)
    assert r.returncode == 1 and "--suffix" in r.stdout
    assert not out.exists()


def test_cli_reports_tall_headers(tmp_path):
    text = "| a | b |\n| - | - |\n| c | d |\n| e | f |\n| g | h |\n| 1 | 2 |\n"
    (tmp_path / "p001.g00.overview_x.md").write_text(text, encoding="utf-8")
    r = _run(tmp_path, "--out", tmp_path / "x.json")
    assert r.returncode == 0 and "p001.g00(4행)" in r.stdout
