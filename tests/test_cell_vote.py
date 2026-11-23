"""cell_vote: 독립 판독 여러 벌을 칸 단위로 대조해 일치 칸과 갈린 칸을 가른다."""
import csv
import json

import pytest

from _load import load

V = load("scripts/cell_vote.py", "cell_vote")


def grid(rows, header=None):
    g = {"columns": len(rows[0]) if rows else 0, "rows": rows}
    if header is not None:
        g["header"] = header
    return g


def write_reading(path, grids, page="p001"):
    path.write_text(json.dumps({"page": page, "grids": grids}, ensure_ascii=False), encoding="utf-8")
    return path


# ---- 정규화 ----

@pytest.mark.parametrize("raw, want", [
    ("  12.5  ", "12.5"),
    ("１２", "12"),            # NFKC: 전각 숫자
    ("10 – 20", "10 - 20"),     # en dash
    ("10—20", "10-20"),         # em dash
    ("−5", "-5"),               # 수학 기호 빼기
    ("a   b\tc", "a b c"),      # 연속 공백
    ("12,5", "12.5"),           # 숫자와 쉼표 하나 → 소수점
    ("1,000,000", "1,000,000"),  # 쉼표 둘 이상은 그대로
    ("1-1/4", "1 1/4"),         # 대분수
    ("32 - 3/4", "32 3/4"),
    ("1¼", "1 1/4"),            # 유니코드 분수 글자
    ("-", "-"),
    ("", ""),
])
def test_normalize(raw, want):
    assert V.normalize(raw) == (want, False)


def test_normalize_question_mark_records_uncertainty():
    assert V.normalize("36?") == ("36", True)
    assert V.normalize(" 36 ? ") == ("36", True)
    assert V.normalize("36？") == ("36", True)  # 전각 물음표


def test_blank_and_dash_differ():
    assert V.normalize("")[0] != V.normalize("-")[0]


def test_fraction_spelling_is_one_value():
    assert V.normalize("32-3/4")[0] == V.normalize("32 3/4")[0]


def test_normalize_cache_keeps_similar_strings_apart():
    # 정규화 결과를 글자열 기준으로 캐시해도 비슷한 글자열끼리 섞이지 않고, 두 번 불러도 같다
    seen = ["12", "１２", "12?", " 12 ", "1,5", "1.5", "1,500", "1-1/4", "1 1/4", "25¹", "251", "-", ""]
    first = [V.normalize(v) for v in seen]
    assert [V.normalize(v) for v in seen] == first
    assert first[:3] == [("12", False), ("12", False), ("12", True)]
    assert first[4] == first[5] == ("1.5", False) and first[6] == ("1,500", False)
    assert first[9] != first[10]
    assert V.normalize(None) == V.normalize("") and V.normalize(12) == V.normalize("12")


def test_repeated_values_still_surface_disagreement():
    # 같은 글자열이 여러 칸에 되풀이돼도 칸마다 따로 갈림을 가른다(정규화 캐시가 불일치를 숨기지 않음)
    rows = [["6", "6", "6", "6"]] * 3
    rep = V.vote({"a": {"g": grid(rows)},
                  "b": {"g": grid([["6", "8", "6", "6"]] * 3)},
                  "c": {"g": grid([["6", "6", "6", "6"]] * 3)}})
    assert rep["summary"]["categories"]["unanimous"] == 9
    assert rep["summary"]["categories"]["majority"] == 3
    assert rep["summary"]["pairwise_diff"] == {"a|b": 3, "a|c": 0, "b|c": 3}
    assert {(it["row"], it["col"]) for it in rep["review"]} == set()


# ---- 칸 분류 ----

def test_three_readings_majority():
    c = V.classify_cell({"a": "68", "b": "68", "c": "86"})
    assert c["category"] == "majority"
    assert c["consensus"] == "68"


def test_unanimous_after_normalization_keeps_first_raw():
    c = V.classify_cell({"a": "32-3/4", "b": "32 3/4"})
    assert c["category"] == "unanimous"
    assert c["consensus"] == "32-3/4"
    assert c["flags"] == []


def test_two_readings_differ_is_tie():
    c = V.classify_cell({"a": "36", "b": "38"})
    assert c["category"] == "tie"
    assert c["consensus"] is None
    assert "confusable:6/8" in c["flags"]


def test_all_differ():
    c = V.classify_cell({"a": "1", "b": "2", "c": "3"})
    assert c["category"] == "all_differ"
    assert c["consensus"] is None


def test_same_family_majority_is_demoted():
    fam = {"sonnet": "claude", "opus": "claude", "gpt": "openai"}
    c = V.classify_cell({"sonnet": "36", "opus": "36", "gpt": "38"}, fam)
    assert c["category"] == "majority_same_family"
    assert c["consensus"] is None


def test_cross_family_majority_stays_majority():
    fam = {"sonnet": "claude", "opus": "claude", "gpt": "openai"}
    c = V.classify_cell({"sonnet": "36", "opus": "38", "gpt": "38"}, fam)
    assert c["category"] == "majority"
    assert c["consensus"] == "38"


def test_without_family_no_demotion():
    c = V.classify_cell({"sonnet": "36", "opus": "36", "gpt": "38"})
    assert c["category"] == "majority"


def test_four_readings_two_two_is_tie():
    c = V.classify_cell({"a": "1", "b": "1", "c": "2", "d": "2"})
    assert c["category"] == "tie"


def test_uncertain_mark_flag_even_when_unanimous():
    c = V.classify_cell({"a": "36?", "b": "36"})
    assert c["category"] == "unanimous"
    assert "uncertain_mark" in c["flags"]
    assert c["review"] is True


def test_plain_unanimous_not_reviewed():
    assert V.classify_cell({"a": "36", "b": "36"})["review"] is False


def test_majority_not_reviewed():
    assert V.classify_cell({"a": "36", "b": "36", "c": "38"})["review"] is False


def test_confusable_pair_order_is_sorted():
    assert "confusable:5/6" in V.classify_cell({"a": "165", "b": "166"})["flags"]


def test_two_char_difference_not_confusable():
    flags = V.classify_cell({"a": "36", "b": "58"})["flags"]
    assert not any(f.startswith("confusable") for f in flags)


def test_non_confusable_digit_pair_not_flagged():
    flags = V.classify_cell({"a": "16", "b": "14"})["flags"]  # 4/6은 혼동 쌍 목록에 없다
    assert not any(f.startswith("confusable") for f in flags)


def test_decimal_point_flag():
    assert "decimal_point" in V.classify_cell({"a": "50.0", "b": "500"})["flags"]
    assert "decimal_point" in V.classify_cell({"a": "5.00", "b": "50.0"})["flags"]


def test_text_flag():
    assert "text" in V.classify_cell({"a": "Flat", "b": "Flats"})["flags"]
    assert "text" in V.classify_cell({"a": "", "b": "-"})["flags"]


# ---- 격자 맞추기와 보고서 ----

def test_positional_vote_and_consensus():
    r = V.vote({
        "a": {"g": grid([["1", "10"], ["2", "36"]], ["SIZE", "O"])},
        "b": {"g": grid([["1", "10"], ["2", "38"]])},
    })
    g = r["grids"]["g"]
    assert g["status"] == "aligned"
    assert g["consensus"] == [["1", "10"], ["2", None]]
    assert r["summary"]["cell_count"] == 4
    assert r["summary"]["categories"]["unanimous"] == 3
    assert r["summary"]["categories"]["tie"] == 1
    assert r["summary"]["pairwise_diff"] == {"a|b": 1}
    [item] = r["review"]
    assert item["grid"] == "g" and item["row"] == 1 and item["col"] == 1
    assert item["row_label"] == "2"
    assert item["column_header"] == "O"
    assert item["values"] == {"a": "36", "b": "38"}
    assert item["category"] == "tie"


def test_caution_string_at_top():
    r = V.vote({"a": {"g": grid([["1"]])}, "b": {"g": grid([["1"]])}})
    assert list(r)[0] == "caution"
    assert "정답 보증이 아니다" in r["caution"]


def test_reading_missing_one_column_is_realigned():
    full = [["1/2", "90", "9.6", "30"], ["3/4", "100", "11.2", "38"],
            ["1", "110", "12.7", "49"], ["1 1/4", "115", "14.3", "59"]]
    short = [[r[0], r[1], r[3]] for r in full]  # 세 번째 열(9.6…)을 빠뜨린 판독
    short[2][2] = "48"
    r = V.vote({"a": {"g": grid(full)}, "b": {"g": grid(short)}})
    g = r["grids"]["g"]
    assert g["status"] == "realigned"
    assert g["reference"] == "a"
    assert g["col_maps"]["b"] == [[0, 0], [1, 1], [3, 2]]
    assert g["unmatched"]["b"]["reference_cols"] == [2]
    # 빠진 열(2)과 그 이웃 열(1·3)은 대응이 미심쩍으므로 확정하지 않는다
    assert g["consensus"][0] == ["1/2", None, None, None]
    assert g["consensus"][2][3] is None
    assert r["summary"]["categories"]["single_reading"] == 4
    assert r["summary"]["categories"]["tie"] == 1
    singles = [it for it in r["review"] if it["category"] == "single_reading"]
    assert len(singles) == 4
    edge = [it for it in r["review"] if it["col"] == 1]
    assert edge and all("alignment_edge" in it["flags"] for it in edge)


def test_reading_missing_one_row_is_realigned():
    full = [["1", "10", "20"], ["2", "11", "21"], ["3", "12", "22"], ["4", "13", "23"]]
    short = [full[0], full[1], full[3]]
    r = V.vote({"a": {"g": grid(full)}, "b": {"g": grid(short)}})
    g = r["grids"]["g"]
    assert g["status"] == "realigned"
    assert g["row_maps"]["b"] == [[0, 0], [1, 1], [3, 2]]
    assert g["unmatched"]["b"]["reference_rows"] == [2]


def test_structure_mismatch_skips_cells():
    a = [["1", "2", "3", "4", "5", "6"]] * 3
    b = [["9", "8"]] * 3
    r = V.vote({"a": {"g": grid(a)}, "b": {"g": grid(b)}})
    assert r["grids"]["g"]["status"] == "structure_mismatch"
    assert r["summary"]["structure_mismatch"] == ["g"]
    assert r["summary"]["cell_count"] == 0
    assert r["review"] == []


def test_low_match_ratio_is_structure_mismatch():
    a = [["1", "2", "3"], ["4", "5", "6"]]
    b = [["7", "8"], ["9", "0"]]
    r = V.vote({"a": {"g": grid(a)}, "b": {"g": grid(b)}})
    assert r["grids"]["g"]["status"] == "structure_mismatch"


def test_grid_missing_in_one_of_three_readings():
    g = grid([["1", "36"]])
    r = V.vote({"a": {"g": g, "h": g}, "b": {"g": g, "h": g}, "c": {"g": g}})
    assert r["grids"]["h"]["missing_readings"] == ["c"]
    assert r["grids"]["h"]["status"] == "aligned"
    assert r["summary"]["grid_count"] == 2


def test_grid_missing_in_one_of_two_readings_is_not_compared():
    g = grid([["1", "36"]])
    r = V.vote({"a": {"g": g, "h": g}, "b": {"g": g}})
    assert r["grids"]["h"]["status"] == "insufficient_readings"
    assert r["summary"]["aligned_count"] == 1
    assert r["summary"]["cell_count"] == 2


def test_same_family_flows_into_review():
    g1, g2 = grid([["36"]]), grid([["38"]])
    r = V.vote({"s": {"g": g1}, "o": {"g": g1}, "x": {"g": g2}},
               {"s": "claude", "o": "claude", "x": "openai"})
    assert r["summary"]["categories"]["majority_same_family"] == 1
    assert r["review"][0]["category"] == "majority_same_family"
    assert r["summary"]["readings"] == [
        {"name": "s", "family": "claude"}, {"name": "o", "family": "claude"},
        {"name": "x", "family": "openai"}]


# ---- 입력과 명령줄 ----

def test_folder_and_file_inputs(tmp_path, capsys):
    d = tmp_path / "sonnet"
    d.mkdir()
    write_reading(d / "p001.json", {"p001.g00": grid([["1", "36"]], ["SIZE", "O"])})
    write_reading(d / "p002.json", {"p002.g00": grid([["2", "50.0"]])}, "p002")
    f = write_reading(tmp_path / "opus.json", {
        "p001.g00": grid([["1", "38?"]]), "p002.g00": grid([["2", "50,0"]])})
    out = tmp_path / "out" / "report.json"
    rc = V.main(["--reading", f"sonnet={d}", "--reading", f"opus={f}", "--out", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["summary"]["grid_count"] == 2
    assert rep["summary"]["cell_count"] == 4
    assert rep["summary"]["review_count"] == 1
    item = rep["review"][0]
    assert item["values"] == {"sonnet": "36", "opus": "38?"}
    assert "uncertain_mark" in item["flags"] and "confusable:6/8" in item["flags"]
    text = capsys.readouterr().out
    assert "재확인" in text and "정답 보증이 아니다" in text


def test_csv_output(tmp_path):
    a = write_reading(tmp_path / "a.json", {"g": grid([["1", "36"]], ["SIZE", "O"])})
    b = write_reading(tmp_path / "b.json", {"g": grid([["1", "38"]])})
    out, c = tmp_path / "r.json", tmp_path / "r.csv"
    assert V.main(["--reading", f"a={a}", "--reading", f"b={b}", "--out", str(out), "--csv", str(c)]) == 0
    raw = c.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(c.open(encoding="utf-8-sig")))
    assert len(rows) == 1
    assert rows[0]["grid"] == "g" and rows[0]["a"] == "36" and rows[0]["b"] == "38"
    assert rows[0]["column_header"] == "O"
    assert "confusable:6/8" in rows[0]["flags"]


def test_only_one_reading_is_input_error(tmp_path, capsys):
    a = write_reading(tmp_path / "a.json", {"g": grid([["1"]])})
    assert V.main(["--reading", f"a={a}", "--out", str(tmp_path / "r.json")]) == 1
    assert "2벌" in capsys.readouterr().err


def test_missing_path_is_input_error(tmp_path, capsys):
    a = write_reading(tmp_path / "a.json", {"g": grid([["1"]])})
    rc = V.main(["--reading", f"a={a}", "--reading", f"b={tmp_path / 'nope'}", "--out", str(tmp_path / "r.json")])
    assert rc == 1
    assert "없" in capsys.readouterr().err


def test_bad_json_is_input_error(tmp_path, capsys):
    a = write_reading(tmp_path / "a.json", {"g": grid([["1"]])})
    b = tmp_path / "b.json"
    b.write_text("{not json", encoding="utf-8")
    assert V.main(["--reading", f"a={a}", "--reading", f"b={b}", "--out", str(tmp_path / "r.json")]) == 1
    assert "JSON" in capsys.readouterr().err


def test_wrong_shape_json_is_input_error(tmp_path):
    a = write_reading(tmp_path / "a.json", {"g": grid([["1"]])})
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"page": "p1", "grids": {"g": {"columns": 2, "rows": [["1"]]}}}), encoding="utf-8")
    assert V.main(["--reading", f"a={a}", "--reading", f"b={b}", "--out", str(tmp_path / "r.json")]) == 1


def test_bad_reading_spec_and_missing_args_exit_1(tmp_path):
    a = write_reading(tmp_path / "a.json", {"g": grid([["1"]])})
    assert V.main(["--reading", str(a), "--reading", f"b={a}", "--out", str(tmp_path / "r.json")]) == 1
    assert V.main(["--reading", f"a={a}", "--reading", f"b={a}"]) == 1  # --out 없음
    assert V.main(["--reading", f"a={a}", "--reading", f"a={a}", "--out", str(tmp_path / "r.json")]) == 1


def test_family_for_unknown_reading_is_error(tmp_path):
    a = write_reading(tmp_path / "a.json", {"g": grid([["1"]])})
    rc = V.main(["--reading", f"a={a}", "--reading", f"b={a}", "--family", "z=claude",
                 "--out", str(tmp_path / "r.json")])
    assert rc == 1


# ---- 리뷰 반영: 불변식 (가)~(라) ----
#   (가) consensus에 값이 있는 칸은 재확인 목록에 없다. 재확인 칸의 consensus는 null이다.
#   (나) consensus가 null인 칸은 모두 재확인 목록에 있다.
#   (다) 어느 판독에든 있는 행·열은 합의 격자나 재확인 목록 어딘가에 드러난다.
#   (라) 분류별 칸 수의 합 = cell_count = 격자 칸 수의 합.

FAM5 = {"o1": "ocr", "o2": "ocr", "g": "google", "c1": "claude", "c2": "claude"}


def check_invariants(rep, readings):
    s = rep["summary"]
    assert sum(s["categories"].values()) == s["cell_count"]
    grid_cells = sum(len(row) for g in rep["grids"].values() for row in g.get("consensus", []))
    assert grid_cells == s["cell_count"]
    at = {(it["grid"], it["row"], it["col"]) for it in rep["review"] if it["row"] is not None}
    for gid, g in rep["grids"].items():
        if "consensus" not in g:
            continue
        for i, row in enumerate(g["consensus"]):
            for j, v in enumerate(row):
                assert (v is None) == ((gid, i, j) in at), (gid, i, j, v)
        excluded = set(g.get("excluded_readings", []))
        for n, rd in readings.items():
            if gid not in rd or n in excluded:
                continue
            rows, cols = len(rd[gid]["rows"]), rd[gid]["columns"]
            rmap = dict(map(tuple, g.get("row_maps", {}).get(n, [[k, k] for k in range(rows)])))
            cmap = dict(map(tuple, g.get("col_maps", {}).get(n, [[k, k] for k in range(cols)])))
            seen = {(k, kk) for k in rmap.values() for kk in cmap.values()}
            seen |= {(it["reading_row"], it["reading_col"]) for it in rep["review"]
                     if it["grid"] == gid and it.get("reading") == n}
            missing = {(k, kk) for k in range(rows) for kk in range(cols)} - seen
            assert not missing, (gid, n, sorted(missing)[:5])


def test_invariants_random():
    import random
    rng = random.Random(11)
    fams = ["ocr", "google", "claude"]
    for _ in range(400):
        nr, nc = rng.randint(1, 7), rng.randint(1, 6)
        kind = rng.choice(["rand", "repeat"])
        if kind == "rand":
            truth = [[str(rng.randint(1, 99)) for _ in range(nc)] for _ in range(nr)]
        else:
            base = [str(rng.randint(1, 9)) for _ in range(nc)]
            truth = [[str(i + 1)] + base[1:] for i in range(nr)]
        readings, families = {}, {}
        for r in range(rng.randint(2, 5)):
            name = "r%d" % r
            families[name] = rng.choice(fams)
            rows = [list(x) for x in truth]
            if rng.random() < 0.3 and len(rows) > 1:
                rows.pop(rng.randrange(len(rows)))
            if rng.random() < 0.2 and nc > 1:
                drop = rng.randrange(nc)
                rows = [[c for j, c in enumerate(x) if j != drop] for x in rows]
            if rng.random() < 0.3 and nc > 1:
                rows = [x + [str(rng.randint(1, 9))] for x in rows]  # 열이 하나 더 많은 판독
            for x in rows:
                for j in range(len(x)):
                    if rng.random() < 0.1:
                        x[j] = rng.choice(["", "-", "8", x[j] + "?", x[j].replace("6", "8")])
            g = {"columns": len(rows[0]) if rows else 0, "rows": rows, "header": None}
            readings[name] = {} if rng.random() < 0.1 else {"g": g}
        rep = V.vote(readings, families if rng.random() < 0.7 else None)
        check_invariants(rep, readings)


def test_question_marked_unanimous_has_no_consensus():
    r = V.vote({"a": {"g": grid([["36?"]])}, "b": {"g": grid([["36"]])}})
    assert r["grids"]["g"]["consensus"] == [[None]]
    assert r["review"][0]["values"] == {"a": "36?", "b": "36"}


def test_single_reading_is_reviewed():
    c = V.classify_cell({"a": "36"})
    assert c["category"] == "single_reading" and c["review"] is True and c["consensus"] is None


def test_plurality():
    c = V.classify_cell({"a": "1", "b": "1", "c": "2", "d": "3"})
    assert c["category"] == "plurality" and c["consensus"] is None and c["review"] is True


# ---- 계열 3개·판독 5벌 ----

@pytest.mark.parametrize("values, want", [
    ({"o1": "1", "o2": "1", "g": "1", "c1": "1", "c2": "1"}, "unanimous"),
    ({"o1": "1", "o2": "1", "g": "1", "c1": "2", "c2": "2"}, "majority"),       # 3:2
    ({"o1": "1", "o2": "1", "c1": "1", "g": "2", "c2": "2"}, "majority"),       # 3:2 계열 섞임
    ({"o1": "1", "o2": "1", "c1": "2", "c2": "2", "g": "3"}, "tie"),            # 2:2:1
    ({"c1": "1", "c2": "1", "o1": "2", "o2": "3", "g": "4"}, "plurality"),      # 2:1:1:1
    ({"c1": "1", "c2": "1", "g": "2"}, "majority_same_family"),
    ({"c1": "1", "c2": "1"}, "majority_same_family"),                           # 다른 계열이 그 칸에 없음
    ({"o1": "1", "o2": "1", "c1": "2"}, "majority_same_family"),
    ({"c1": "1", "c2": "1", "o1": "2", "o2": "2"}, "tie"),
])
def test_five_readings_three_families(values, want):
    assert V.classify_cell(values, FAM5)["category"] == want


def test_single_family_run_keeps_unanimous():
    fam = {"sonnet": "claude", "opus": "claude"}
    c = V.classify_cell({"sonnet": "36", "opus": "36"}, fam)
    assert c["category"] == "unanimous" and c["consensus"] == "36"


def test_grid_only_in_one_family_is_not_confirmed():
    g = grid([["1", "36"], ["2", "38"]])
    rd = {"o1": {"h": g}, "o2": {"h": g}, "g": {"h": g}, "c1": {"g": g, "h": g}, "c2": {"g": g, "h": g}}
    r = V.vote(rd, FAM5)
    assert r["grids"]["g"]["consensus"] == [[None, None], [None, None]]
    assert r["summary"]["categories"]["majority_same_family"] == 4


def test_cells_other_family_lacks_are_not_confirmed():
    full = [["1/2", "90", "9.6", "30"], ["3/4", "100", "11.8", "38"],
            ["1", "110", "12.7", "49"], ["1 1/4", "115", "14.3", "59"], ["1 1/2", "125", "15.9", "65"]]
    short = [[x[0], x[1], x[3]] for x in full]
    r = V.vote({"c1": {"g": grid(full)}, "c2": {"g": grid(full)}, "g": {"g": grid(short)}}, FAM5)
    assert all(row[2] is None for row in r["grids"]["g"]["consensus"])


# ---- 재정렬 ----

def test_rows_only_in_minority_shape_surface():
    full = [["1", "10", "20"], ["2", "11", "21"], ["3", "12", "22"], ["4", "13", "23"]]
    short = [full[0], full[1], full[3]]
    rd = {"o": {"g": grid(short)}, "x": {"g": grid(short)}, "s": {"g": grid(full)}}
    r = V.vote(rd)
    g = r["grids"]["g"]
    assert g["reference"] == "s"
    assert len(g["consensus"]) == 4
    assert [it["category"] for it in r["review"] if it["row"] == 2] == ["single_reading"] * 3
    check_invariants(r, rd)


def test_reading_with_extra_column_and_fewer_rows_surfaces_everything():
    a = [["1", "10", "20"], ["2", "11", "21"], ["3", "12", "22"], ["4", "13", "23"]]
    b = [x + ["9"] for x in (a[0], a[1], a[3])]  # 행은 하나 적고 열은 하나 많다
    rd = {"a": {"g": grid(a)}, "b": {"g": grid(b)}}
    r = V.vote(rd)
    assert r["grids"]["g"]["status"] == "realigned"
    extra = [it for it in r["review"] if it.get("reading") == "b"]
    assert extra and all(it["category"] == "unaligned" for it in extra)
    check_invariants(r, rd)


def test_neighbor_rows_of_gap_are_not_confirmed():
    truth = [["1", "10", "11"], ["2", "20", "21"], ["3", "29", "13"], ["4", "29", "13"], ["5", "40", "41"]]
    a = [list(x) for x in truth]
    a[3][0] = "3"                      # 4를 3으로 오독
    b = [truth[i] for i in (0, 1, 2, 4)]  # 4행을 통째로 빠뜨림
    r = V.vote({"a": {"g": grid(a)}, "b": {"g": grid(b)}})
    cons = r["grids"]["g"]["consensus"]
    assert cons[3] == [None, None, None]
    assert cons[2] == [None, None, None]
    assert cons[0] == ["1", "10", "11"]
    assert any("alignment_edge" in it["flags"] for it in r["review"])


def test_sparse_reading_does_not_pass_ratio():
    a = [["11", "12", "13", "14", "15", "16"], ["21", "22", "23", "24", "25", "26"],
         ["31", "32", "33", "34", "35", "36"]]
    b = [["", "22", "23", "", "", ""]]
    r = V.vote({"a": {"g": grid(a)}, "b": {"g": grid(b)}})
    assert r["grids"]["g"]["status"] == "structure_mismatch"


def test_failed_reading_is_excluded_when_two_remain():
    g = grid([["1", "10", "36"], ["2", "11", "37"], ["3", "12", "38"], ["4", "13", "39"]])
    bad = grid([["x", "y"], ["z", "w"], ["p", "q"], ["r", "s"]])
    r = V.vote({"a": {"g": g}, "b": {"g": g}, "c": {"g": bad}})
    rec = r["grids"]["g"]
    assert rec["status"] == "aligned"
    assert rec["excluded_readings"] == ["c"]
    assert r["summary"]["cell_count"] == 12
    assert r["summary"]["categories"]["unanimous"] == 12


def test_exclusion_leaving_one_family_is_not_confirmed():
    g = grid([["1", "10", "36"], ["2", "11", "37"], ["3", "12", "38"], ["4", "13", "39"]])
    bad = grid([["x", "y"], ["z", "w"], ["p", "q"], ["r", "s"]])
    r = V.vote({"c1": {"g": g}, "c2": {"g": g}, "o1": {"g": bad}}, FAM5)
    assert r["grids"]["g"]["excluded_readings"] == ["o1"]
    assert r["summary"]["categories"]["majority_same_family"] == 12


def test_exclusion_leaving_one_reading_is_mismatch():
    g = grid([["1", "10", "36"], ["2", "11", "37"]])
    r = V.vote({"a": {"g": g}, "b": {"g": grid([["x", "y", "z", "w", "v", "u"]])},
                "c": {"g": grid([["p"]])}})
    assert r["grids"]["g"]["status"] == "structure_mismatch"


def test_row_shift_suspect():
    labels = [str(i) for i in range(1, 10)]
    a = [[x, "5"] for x in labels if x != "3"]
    b = [[x, "5"] for x in labels if x != "7"]
    r = V.vote({"a": {"g": grid(a)}, "b": {"g": grid(b)}})
    assert r["grids"]["g"]["row_shift_suspect"] == [[2, 5]]


# ---- 합쳐지면 안 되는 값 ----

@pytest.mark.parametrize("a, b", [
    ("1 1/4", "11/4"),
    ("1,250", "1.250"),
    ("1,000", "1.000"),
    ("25¹", "251"),
    ("10²", "102"),
    ("25①", "251"),
    ("H₂", "H2"),
    ("+0 -1/8", "+0 1/8"),
    ("5 -1/2", "5 1/2"),
])
def test_values_that_must_not_merge(a, b):
    assert V.normalize(a)[0] != V.normalize(b)[0]


@pytest.mark.parametrize("a, b", [("12,5", "12.5"), ("0,75", "0.75"), ("1 - 1/4", "1 1/4")])
def test_values_that_still_merge(a, b):
    assert V.normalize(a)[0] == V.normalize(b)[0]


# ---- 명령줄 ----

def test_family_cli_run(tmp_path):
    g1, g2 = grid([["1", "36"]]), grid([["1", "38"]])
    s = write_reading(tmp_path / "s.json", {"g": g1})
    o = write_reading(tmp_path / "o.json", {"g": g1})
    x = write_reading(tmp_path / "x.json", {"g": g2})
    out = tmp_path / "r.json"
    rc = V.main(["--reading", f"s={s}", "--reading", f"o={o}", "--reading", f"x={x}",
                 "--family", "s=claude", "--family", "o=claude", "--family", "x=openai",
                 "--out", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["summary"]["categories"]["majority_same_family"] == 1
    assert rep["grids"]["g"]["consensus"] == [["1", None]]  # "1"은 계열을 넘는 전원일치


def test_bom_input_is_read(tmp_path):
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"grids": {"g": grid([["1"]])}}), encoding="utf-8-sig")
    b = write_reading(tmp_path / "b.json", {"g": grid([["1"]])})
    assert V.main(["--reading", f"a={a}", "--reading", f"b={b}", "--out", str(tmp_path / "r.json")]) == 0


def test_unwritable_out_is_error(tmp_path, capsys):
    a = write_reading(tmp_path / "a.json", {"g": grid([["1"]])})
    rc = V.main(["--reading", f"a={a}", "--reading", f"b={a}", "--out", str(tmp_path)])
    assert rc == 1
    assert "쓰지 못" in capsys.readouterr().err


def test_no_overlap_warns_and_lists(tmp_path, capsys):
    a = write_reading(tmp_path / "a.json", {"p1.g0": grid([["1"]])})
    b = write_reading(tmp_path / "b.json", {"p1.g00": grid([["1"]])})
    assert V.main(["--reading", f"a={a}", "--reading", f"b={b}", "--out", str(tmp_path / "r.json")]) == 0
    text = capsys.readouterr().out
    assert "p1.g0" in text and "p1.g00" in text
    assert "경고" in text


def test_excluded_reading_is_printed(tmp_path, capsys):
    g = grid([["1", "10", "36"], ["2", "11", "37"], ["3", "12", "38"], ["4", "13", "39"]])
    bad = grid([["x", "y"], ["z", "w"], ["p", "q"], ["r", "s"]])
    a = write_reading(tmp_path / "a.json", {"g": g})
    c = write_reading(tmp_path / "c.json", {"g": bad})
    assert V.main(["--reading", f"a={a}", "--reading", f"b={a}", "--reading", f"c={c}",
                   "--out", str(tmp_path / "r.json")]) == 0
    text = capsys.readouterr().out
    assert "g" in text and "c" in text and "뺀 판독" in text


# ---- 재확인 지적 반영 ----

def test_text_label_rows_are_paired_by_label():
    a = [["A", "62", "51"], ["B", "62", "51"], ["C", "62", "51"], ["D", "62", "51"]]
    b = [a[0], a[1], a[3]]  # C행을 빠뜨림
    rd = {"a": {"g": grid(a)}, "b": {"g": grid(b)}, "c": {"g": grid(b)}}
    r = V.vote(rd)
    g = r["grids"]["g"]
    assert g["row_maps"]["b"] == [[0, 0], [1, 1], [3, 2]]
    assert g["consensus"][2][0] is None
    assert all(row[0] != "B" for i, row in enumerate(g["consensus"]) if i != 1)
    check_invariants(r, rd)


def test_partial_family_counts_unnamed_as_own_family():
    g = grid([["1", "36"]])
    rd = {"s": {"g": g, "h": g}, "o": {"g": g, "h": g}, "x": {"h": g}}
    r = V.vote(rd, {"s": "claude", "o": "claude"})
    assert r["grids"]["g"]["consensus"] == [[None, None]]
    assert r["summary"]["categories"]["majority_same_family"] == 2
    assert r["grids"]["h"]["consensus"] == [["1", "36"]]


def test_unspaced_tolerance_keeps_sign():
    assert V.normalize("+0-1/8")[0] != V.normalize("+0 1/8")[0]
    assert V.normalize("-1-1/4")[0] != V.normalize("-1 1/4")[0]


def test_confirmed_count(tmp_path, capsys):
    a = write_reading(tmp_path / "a.json", {"g": grid([["1", "36", "7?"]])})
    b = write_reading(tmp_path / "b.json", {"g": grid([["1", "38", "7"]])})
    out = tmp_path / "r.json"
    assert V.main(["--reading", f"a={a}", "--reading", f"b={b}", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["summary"]["confirmed_count"] == 1
    assert "확정 칸 1" in capsys.readouterr().out
