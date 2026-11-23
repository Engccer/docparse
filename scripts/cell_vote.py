"""독립 판독 여러 벌을 칸 단위로 대조한다 (docparse 칸별 투표).

저해상도 이미지로 박힌 수치표는 한 판독기만으로는 한 글자 숫자 오독(6↔8, 5↔6 등)을
피할 수 없다. 서로 독립적인 판독 2벌 이상을 칸마다 맞대어 일치한 칸과 갈린 칸을 가르고,
확정하지 못한 칸만 재확인 목록으로 내보낸다.

  python cell_vote.py --reading sonnet=<폴더|파일> --reading opus=<폴더|파일> \\
         [--family sonnet=claude --family opus=claude] --out report.json [--csv review.csv]

판독 JSON 한 개: {"page": "p004", "grids": {"p004.g00": {"columns": 15,
  "header": [...], "rows": [[...], ...], "notes": ""}}}. 폴더를 주면 안의 *.json을
격자 id로 합친다. 판독자가 자신 없는 칸은 값 끝에 `?`를 붙인다.

보고서가 지키는 불변식:
  (가) consensus에 값이 있는 칸은 재확인 목록에 없다. 재확인 칸의 consensus는 null이다
       (`?`가 붙은 전원일치·과반 포함. 후보 값은 재확인 항목의 values로 본다).
  (나) consensus가 null인 칸은 모두 재확인 목록에 있다(single_reading 포함).
  (다) 어느 판독에든 있는 행·열은 합의 격자나 재확인 목록 어딘가에 드러난다.
       예외는 격자 기록의 excluded_readings(구조를 못 맞춰 뺀 판독), structure_mismatch 격자,
       한 벌에만 있는 insufficient_readings 격자다(셋 다 요약·표준 출력에 격자 id가 나온다).
  (라) 분류별 칸 수의 합 = cell_count = 격자 칸 수의 합.

주의: 일치는 정답 보증이 아니다. 판독자들이 같은 방식으로 틀린 칸은 드러나지 않는다.
같은 계열 모델이 같은 방식으로 틀리는 일이 실측됐으므로, --family로 계열을 주면(지정 안 된
판독은 자기 이름을 계열로 삼는다) 계열이 2개 이상일 때 한 계열만으로 이룬 전원일치·과반은
확정하지 않고 재확인으로 돌린다(majority_same_family).

종료 코드: 0 = 정상, 1 = 입력 오류(판독 1벌 이하, 경로 없음, JSON 형식 오류,
결과 파일 쓰기 실패 등). 표준 라이브러리만 쓴다.
"""
import argparse
import collections
import csv
import functools
import itertools
import json
import pathlib
import re
import sys
import unicodedata

CAUTION = ("일치는 정답 보증이 아니다. 판독자들이 같은 방식으로 틀린 칸은 "
           "이 대조로 드러나지 않는다.")

# 저해상도 스캔에서 실측된 숫자 혼동 쌍(작은 숫자를 앞에 둔 표기)
CONFUSABLE = {frozenset(p) for p in (
    "68", "56", "89", "38", "08", "06", "17", "27", "48", "23",
    "58", "35", "09", "39", "24", "13")}

MAX_SHAPE_DIFF = 2        # 행·열 수 차이가 이 이하일 때만 다시 맞추기를 시도한다
MIN_MATCH_RATIO = 0.75    # 다시 맞춘 대응의 숫자 칸 일치율이 이 값을 넘어야 쓴다
SHIFT_RUN = 3             # 첫 열이 연속 이만큼 갈리면 행 밀림을 의심한다

CATEGORIES = ("unanimous", "majority", "majority_same_family", "plurality",
              "tie", "all_differ", "single_reading")
CONFIRMED = ("unanimous", "majority")
SPLIT = ("plurality", "tie", "all_differ")

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―⁃−﹘"), "-")
_VULGAR = "¼½¾⅐⅑⅒⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞"
# 대시 앞뒤 공백이 대칭일 때만 대분수로 본다(`1-1/4`, `1 - 1/4`). `+0 -1/8`의 부호는 남기고,
# 부호가 앞에 붙은 수(`+0-1/8`, `-1-1/4`)는 공차 표기일 수 있어 대분수로 보지 않는다.
_MIXED = re.compile(r"(?<![\d/+\-±])(\d+)(?:-| - )(\d+/\d+)")
_SCRIPT = {"<super>": "^%s", "<sub>": "_%s", "<circle>": "(%s)"}
# normalize가 칸마다 쓰는 정규식은 한 번만 컴파일한다
_VULGAR_GAP = re.compile(r"(\d)\s*([%s])" % _VULGAR)
_SPACES = re.compile(r"\s+")
_COMMA_NUM = re.compile(r"\d+,\d+")
_COMMA_THOUSANDS = re.compile(r"\d+,\d{3}")


class InputError(Exception):
    """입력 오류: 종료 코드 1로 끝낸다."""


# ---- 정규화 ----

def _mark_script(ch):
    """위첨자·아래첨자·원문자를 본문 글자와 구별되는 표기로 바꾼다(`¹`→`^1`, `①`→`(1)`)."""
    d = unicodedata.decomposition(ch)
    fmt = _SCRIPT.get(d.split(" ", 1)[0]) if d.startswith("<") else None
    return fmt % unicodedata.normalize("NFKC", ch) if fmt else ch


@functools.lru_cache(maxsize=1 << 16)
def _normalize_str(s):
    """normalize의 본체. 같은 글자열은 같은 결과라 캐시한다(결과가 튜플이라 공유해도 안전하다)."""
    if not s.isascii():
        # NFKC가 `25¹`을 `251`로 접으므로 그 전에 첨자·원문자를 구별되는 표기로 바꾼다
        s = "".join(_mark_script(c) if ord(c) > 127 else c for c in s)
        # NFKC가 `1¼`을 `11⁄4`로 붙여 버리므로 분수 글자 앞에 먼저 띄어쓰기를 둔다
        s = _VULGAR_GAP.sub(r"\1 \2", s)
        s = unicodedata.normalize("NFKC", s).replace("⁄", "/").translate(_DASHES)
    # ASCII 글자열은 위 단계가 모두 항등이라 건너뛴다
    s = s.strip()
    uncertain = False
    while s.endswith("?"):
        s = s[:-1].rstrip()
        uncertain = True
    s = _SPACES.sub(" ", s)
    # 쉼표 소수점은 합치되, 쉼표 뒤가 정확히 3자리면 천 단위 구분일 수 있어 그대로 둔다
    if "," in s and _COMMA_NUM.fullmatch(s) and not _COMMA_THOUSANDS.fullmatch(s):
        s = s.replace(",", ".")
    if "-" in s:  # _MIXED는 대시가 있어야만 맞는다
        s = _MIXED.sub(r"\1 \2", s)
    return s, uncertain


def normalize(value):
    """비교용 정규화. (정규화한 값, 끝에 `?` 표시가 있었는가)를 돌려준다."""
    return _normalize_str("" if value is None else str(value))


def _clean_raw(raw):
    """합의값으로 내보낼 원문: 앞뒤 공백과 끝의 `?`만 걷는다."""
    s = ("" if raw is None else str(raw)).strip()
    while s.endswith(("?", "？")):
        s = s[:-1].rstrip()
    return s


def _has_digit(s):
    return any(ch.isdigit() for ch in s)


# ---- 칸 분류 ----

def _pair_flags(a, b):
    flags = []
    if len(a) == len(b):
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        if len(diff) == 1 and frozenset(diff[0]) in CONFUSABLE:
            flags.append("confusable:%s/%s" % tuple(sorted(diff[0])))
    if _has_digit(a) and _has_digit(b) and a.replace(".", "") == b.replace(".", ""):
        flags.append("decimal_point")
    return flags


def classify_cell(values, families=None):
    """판독별 원문 값 {이름: 값}을 분류한다.

    families(이름→계열)에 계열이 2개 이상이면, 전원일치·과반을 이룬 판독이 모두 한
    계열일 때 다른 계열이 그 칸에 값을 냈는지와 무관하게 majority_same_family로 강등한다.
    계열이 하나뿐이면 다른 계열 판독이 다른 값을 냈을 때만 강등한다.
    판독 이름이 families에 없으면 그 이름 자체를 계열로 본다.
    """
    return _classify(values, {name: normalize(v) for name, v in values.items()}, families)


def _classify(values, normed, families):
    """classify_cell의 본체. normed({이름: normalize 결과})를 호출자가 이미 구했을 때 쓴다."""
    flags = []
    if any(unc for _, unc in normed.values()):
        flags.append("uncertain_mark")
    n = len(normed)
    if n < 2:
        return {"category": "single_reading", "consensus": None, "flags": flags, "review": True}

    groups = collections.OrderedDict()
    for name, (val, _) in normed.items():
        groups.setdefault(val, []).append(name)
    distinct = list(groups)
    for a, b in itertools.combinations(distinct, 2):
        for f in _pair_flags(a, b):
            if f not in flags:
                flags.append(f)
    if len(distinct) > 1 and not any(_has_digit(v) for v in distinct):
        flags.append("text")

    top = max(groups.values(), key=len)
    tied = sum(1 for g in groups.values() if len(g) == len(top)) > 1
    if len(distinct) == 1:
        category = "unanimous"
    elif len(top) * 2 > n:
        category = "majority"
    elif n == 2 or tied and len(distinct) < n:
        category = "tie"
    elif len(distinct) == n:
        category = "all_differ"
    else:
        category = "plurality"  # 최다 값이 하나지만 과반 미달(판독 4벌 이상에서만 생김)
    if category in CONFIRMED and families:
        fam = lambda r: families.get(r, r)  # noqa: E731
        top_fams = {fam(r) for r in top}
        multi = len(set(families.values())) >= 2
        if len(top_fams) == 1 and (multi or any(fam(r) not in top_fams for r in normed)):
            category = "majority_same_family"
    consensus = None
    if category in CONFIRMED and "uncertain_mark" not in flags:
        consensus = _clean_raw(values[top[0]])
    return {"category": category, "consensus": consensus, "flags": flags,
            "review": consensus is None}


# ---- 격자 맞추기 ----

def _monotone_match(n_ref, n_x, sim):
    """sim[i][k] 합을 최대로 하는 단조 대응 [(i, k), ...]. 같은 점수면 짝을 더 많이 둔다."""
    bonus = 1
    weight = min(n_ref, n_x) + 1  # 일치 칸 1개가 짝 수 보너스 전체보다 무겁게
    D = [[0] * (n_x + 1) for _ in range(n_ref + 1)]
    P = [[None] * (n_x + 1) for _ in range(n_ref + 1)]
    for i in range(1, n_ref + 1):
        for k in range(1, n_x + 1):
            cands = ((D[i - 1][k - 1] + sim[i - 1][k - 1] * weight + bonus, "d"),
                     (D[i - 1][k], "u"), (D[i][k - 1], "l"))
            D[i][k], P[i][k] = max(cands, key=lambda c: c[0])
    pairs, i, k = [], n_ref, n_x
    while i and k:
        step = P[i][k]
        if step == "d":
            pairs.append((i - 1, k - 1))
            i, k = i - 1, k - 1
        elif step == "u":
            i -= 1
        else:
            k -= 1
    return pairs[::-1]


def _same_number(a, b):
    return a == b and _has_digit(a)


def _same_value(a, b):
    """행·열 대응 점수용: 비어 있지 않은 같은 값이면 글자 칸도 센다(글자 라벨로만 갈리는 행)."""
    return a == b and a != ""


def _align(R, X, r_cols, x_cols):
    """판독 X를 기준 R에 맞춘다. 성공하면 (행 대응, 열 대응), 실패하면 None."""
    nr, nx = len(R), len(X)
    if abs(nr - nx) > MAX_SHAPE_DIFF or abs(r_cols - x_cols) > MAX_SHAPE_DIFF:
        return None

    def match_rows(cols):
        sim = [[sum(_same_value(R[i][j], X[k][kk]) for j, kk in cols) for k in range(nx)]
               for i in range(nr)]
        return _monotone_match(nr, nx, sim)

    def match_cols(rows):
        sim = [[sum(_same_value(R[i][j], X[k][kk]) for i, k in rows) for kk in range(x_cols)]
               for j in range(r_cols)]
        return _monotone_match(r_cols, x_cols, sim)

    positional_cols = [(j, j) for j in range(min(r_cols, x_cols))]
    rows = [(i, i) for i in range(nr)] if nr == nx else match_rows(positional_cols)
    cols = [(j, j) for j in range(r_cols)] if r_cols == x_cols else match_cols(rows)
    if nr != nx and r_cols != x_cols:
        rows = match_rows(cols)  # 열 대응을 알았으니 행 대응을 한 번 더 맞춘다
        cols = match_cols(rows)

    # 분모는 대응된 칸 범위의 숫자 칸 수 중 큰 쪽: 성긴 판독이 쉽게 통과하지 못하게
    good = sum(_same_number(R[i][j], X[k][kk]) for i, k in rows for j, kk in cols)
    tot = max(sum(_has_digit(R[i][j]) for i, _ in rows for j, _ in cols),
              sum(_has_digit(X[k][kk]) for _, k in rows for _, kk in cols))
    if not tot or good / tot <= MIN_MATCH_RATIO:
        return None
    return rows, cols


def _shape(g):
    return (len(g["rows"]), g["columns"])


def _choose_alignment(present, norm):
    """기준 판독을 고르고 나머지를 맞춘다. 행·열이 많은 판독부터 기준으로 시도해
    가장 많은 판독을 맞춘 기준을 쓴다. (기준, {이름: (행 대응, 열 대응)}, 못 맞춘 판독)."""
    names = list(present)
    count = collections.Counter(_shape(g) for g in present.values())

    def priority(n):
        r, c = _shape(present[n])
        return (r * c, count[(r, c)], -names.index(n))

    best = None
    for ref in sorted(names, key=priority, reverse=True):
        rs = _shape(present[ref])
        maps, failed = {}, []
        for n in names:
            sh = _shape(present[n])
            if sh == rs:
                maps[n] = ([(i, i) for i in range(sh[0])], [(j, j) for j in range(sh[1])])
                continue
            got = _align(norm[ref], norm[n], rs[1], sh[1])
            if got is None:
                failed.append(n)
            else:
                maps[n] = got
        if best is None or len(maps) > len(best[1]):
            best = (ref, maps, failed)
        if not failed:
            break
    return best


def _edges(ref_shape, x_shape, rows, cols):
    """대응되지 않은 행·열과 그 이웃(기준 좌표). 재정렬이 잘못 짝지었을 수 있는 곳이다."""
    out = []
    for n_ref, n_x, pairs in ((ref_shape[0], x_shape[0], rows), (ref_shape[1], x_shape[1], cols)):
        fwd, inv = dict(pairs), {k: i for i, k in pairs}
        edge = set()
        for i in range(n_ref):
            if i not in fwd:
                edge |= {i - 1, i, i + 1}
        for k in range(n_x):
            if k not in inv:
                edge |= {inv[kk] for kk in (k - 1, k + 1) if kk in inv}
        out.append(edge)
    return out


def _vote_grid(gid, present, missing, families):
    """한 격자를 대조한다. (격자 기록, 칸 결과 목록, 기준 밖 재확인 항목)을 돌려준다."""
    rec = {"status": "", "shapes": {n: list(_shape(g)) for n, g in present.items()},
           "missing_readings": missing}
    if len(present) < 2:
        rec["status"] = "insufficient_readings"
        return rec, [], []

    # 칸마다 정규화하지 않고 격자당 한 번만 한다. 뒤의 칸 분류와 쌍별 비교도 이 결과를 쓴다
    normed = {n: [[normalize(c) for c in row] for row in g["rows"]] for n, g in present.items()}
    norm = {n: [[c[0] for c in row] for row in rows] for n, rows in normed.items()}
    ref, maps, failed = _choose_alignment(present, norm)
    ref_shape = _shape(present[ref])
    if len(maps) < 2:
        rec["status"] = "structure_mismatch"
        rec["reason"] = "어느 판독을 기준으로 잡아도 2벌 이상을 맞추지 못함"
        return rec, [], []
    if failed:
        rec["excluded_readings"] = failed

    realigned = [n for n in maps if _shape(present[n]) != ref_shape]
    rec["status"] = "realigned" if realigned else "aligned"
    edge_rows, edge_cols, extras = set(), set(), []
    for n in realigned:
        g = present[n]
        rows, cols = maps[n]
        rmap, cmap = dict(rows), dict(cols)
        rec["reference"] = ref
        rec.setdefault("row_maps", {})[n] = [list(p) for p in rows]
        rec.setdefault("col_maps", {})[n] = [list(p) for p in cols]
        rec.setdefault("unmatched", {})[n] = {
            "reference_rows": [i for i in range(ref_shape[0]) if i not in rmap],
            "reference_cols": [j for j in range(ref_shape[1]) if j not in cmap],
            "reading_rows": [k for k in range(len(g["rows"])) if k not in rmap.values()],
            "reading_cols": [k for k in range(g["columns"]) if k not in cmap.values()],
        }
        er, ec = _edges(ref_shape, _shape(g), rows, cols)
        edge_rows |= er
        edge_cols |= ec
        # 기준 격자 밖에 남은 이 판독의 칸(기준에 없는 행·열)은 따로 재확인으로 올린다
        mr, mc = set(rmap.values()), set(cmap.values())
        hdr = g.get("header")
        for k, row in enumerate(g["rows"]):
            for kk, raw in enumerate(row):
                if k in mr and kk in mc:
                    continue
                extras.append({"grid": gid, "row": None, "col": None, "reading": n,
                               "reading_row": k, "reading_col": kk,
                               "row_label": _clean_raw(row[0]),
                               "column_header": hdr[kk] if hdr and kk < len(hdr) else None,
                               "values": {n: raw}, "category": "unaligned", "flags": []})

    cells, consensus = [], []
    lookup = {n: (dict(rows), dict(cols)) for n, (rows, cols) in maps.items()}
    for i in range(ref_shape[0]):
        crow = []
        for j in range(ref_shape[1]):
            values, nvals = {}, {}
            for n, (rmap, cmap) in lookup.items():
                if i in rmap and j in cmap:
                    k, kk = rmap[i], cmap[j]
                    values[n] = present[n]["rows"][k][kk]
                    nvals[n] = normed[n][k][kk]
            res = _classify(values, nvals, families)
            if i in edge_rows or j in edge_cols:
                res["flags"].append("alignment_edge")
                res["consensus"], res["review"] = None, True
            res.update(row=i, col=j, values=values, normalized={n: v[0] for n, v in nvals.items()})
            cells.append(res)
            crow.append(res["consensus"])
        consensus.append(crow)
    rec["consensus"] = consensus

    headers = [(present[n].get("header"), lookup[n][1]) for n in maps]

    def header_of(j):
        for h, cmap in headers:
            if h and j in cmap and cmap[j] < len(h):
                return h[cmap[j]]
        return None

    first_col = {c["row"]: c for c in cells if c["col"] == 0}
    for c in cells:
        label = consensus[c["row"]][0]
        first = first_col.get(c["row"])
        if label is None and first and first["values"]:
            label = _clean_raw(next(iter(first["values"].values())))
        c["row_label"] = label
        c["column_header"] = header_of(c["col"])

    # 같은 모양인데 행이 밀렸으면 첫 열(행 라벨)이 연속으로 갈린다
    runs, start = [], None
    for i in range(ref_shape[0] + 1):
        c = first_col.get(i)
        split = c is not None and c["category"] in SPLIT
        if split and start is None:
            start = i
        elif not split and start is not None:
            if i - start >= SHIFT_RUN:
                runs.append([start, i - 1])
            start = None
    if runs:
        rec["row_shift_suspect"] = runs
    return rec, cells, extras


def vote(readings, families=None):
    """판독 {이름: {격자 id: 격자}}를 대조해 보고서 dict를 돌려준다."""
    names = list(readings)
    if families:  # 계열을 하나라도 주면 지정 안 된 판독은 자기 이름을 계열로 삼는다
        families = {n: families.get(n, n) for n in names}
    gids = sorted({gid for r in readings.values() for gid in r})
    cats = collections.Counter({c: 0 for c in CATEGORIES})
    flag_count = collections.Counter()
    pair_keys = [(a, b, "%s|%s" % (a, b)) for a, b in itertools.combinations(names, 2)]
    pair_diff = {key: 0 for _, _, key in pair_keys}
    grids, review, confirmed = {}, [], 0
    for gid in gids:
        present = {n: readings[n][gid] for n in names if gid in readings[n]}
        missing = [n for n in names if gid not in readings[n]]
        rec, cells, extras = _vote_grid(gid, present, missing, families)
        grids[gid] = rec
        for c in cells:
            cats[c["category"]] += 1
            confirmed += c["consensus"] is not None
            flag_count.update(c["flags"])
            normed = c["normalized"]
            for a, b, key in pair_keys:
                if a in normed and b in normed and normed[a] != normed[b]:
                    pair_diff[key] += 1
            if c["review"]:
                review.append({"grid": gid, "row": c["row"], "col": c["col"],
                               "row_label": c["row_label"], "column_header": c["column_header"],
                               "values": {n: c["values"].get(n) for n in names},
                               "category": c["category"], "flags": c["flags"]})
        for it in extras:
            it["values"] = {n: it["values"].get(n) for n in names}
            review.append(it)

    def with_status(*st):
        return [g for g in gids if grids[g]["status"] in st]

    summary = {
        "readings": [{"name": n, "family": (families or {}).get(n)} for n in names],
        "grid_count": len(gids),
        "aligned_count": len(with_status("aligned", "realigned")),
        "realigned": with_status("realigned"),
        "structure_mismatch": with_status("structure_mismatch"),
        "insufficient_readings": with_status("insufficient_readings"),
        "excluded_readings": {g: grids[g]["excluded_readings"] for g in gids
                              if "excluded_readings" in grids[g]},
        "row_shift_suspect": [g for g in gids if "row_shift_suspect" in grids[g]],
        "cell_count": sum(cats.values()),
        "categories": dict(cats),
        "confirmed_count": confirmed,
        "unaligned_count": sum(1 for it in review if it["category"] == "unaligned"),
        "review_count": len(review),
        "flags": dict(flag_count.most_common()),
        "pairwise_diff": pair_diff,
    }
    return {"caution": CAUTION, "summary": summary, "grids": grids, "review": review}


# ---- 입력 ----

def _check_grid(where, gid, g):
    if not isinstance(g, dict) or not isinstance(g.get("rows"), list):
        raise InputError("%s: 격자 %s에 rows 목록이 없습니다" % (where, gid))
    rows = g["rows"]
    if not all(isinstance(r, list) for r in rows):
        raise InputError("%s: 격자 %s의 행이 목록이 아닙니다" % (where, gid))
    cols = g.get("columns", len(rows[0]) if rows else 0)
    if not isinstance(cols, int) or isinstance(cols, bool):
        raise InputError("%s: 격자 %s의 columns가 정수가 아닙니다" % (where, gid))
    for i, r in enumerate(rows):
        if len(r) != cols:
            raise InputError("%s: 격자 %s의 %d번째 행 칸 수 %d가 columns %d와 다릅니다"
                             % (where, gid, i, len(r), cols))
    header = g.get("header")
    return {"columns": cols,
            "rows": [["" if c is None else str(c) for c in r] for r in rows],
            "header": [str(h) for h in header] if isinstance(header, list) else None}


def load_reading(path):
    """판독 하나(파일 또는 *.json 폴더)를 {격자 id: 격자}로 읽는다."""
    p = pathlib.Path(path)
    if not p.exists():
        raise InputError("판독 경로가 없습니다: %s" % p)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    if not files:
        raise InputError("폴더에 판독 JSON(*.json)이 없습니다: %s" % p)
    out = {}
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise InputError("JSON 형식 오류: %s: %s" % (f, e))
        if not isinstance(data, dict) or not isinstance(data.get("grids"), dict):
            raise InputError("%s: 최상위에 grids 객체가 없습니다" % f)
        for gid, g in data["grids"].items():
            if gid in out:
                raise InputError("%s: 격자 id %s가 다른 파일에도 있습니다" % (f, gid))
            out[gid] = _check_grid(f, gid, g)
    return out


def _pairs(specs, what):
    out = {}
    for s in specs or []:
        name, sep, val = s.partition("=")
        name, val = name.strip(), val.strip()
        if not sep or not name or not val:
            raise InputError("%s는 이름=값 꼴이어야 합니다: %s" % (what, s))
        if name in out:
            raise InputError("%s 이름이 겹칩니다: %s" % (what, name))
        out[name] = val
    return out


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError("명령줄 오류: %s" % message)


def write_csv(path, report):
    names = [r["name"] for r in report["summary"]["readings"]]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["grid", "row", "col", "reading", "reading_row", "reading_col", "row_label",
                    "column_header", "category", "flags", *names])
        blank = lambda v: "" if v is None else v  # noqa: E731
        for it in report["review"]:
            w.writerow([it["grid"], blank(it["row"]), blank(it["col"]), blank(it.get("reading")),
                        blank(it.get("reading_row")), blank(it.get("reading_col")),
                        blank(it["row_label"]), blank(it["column_header"]), it["category"],
                        ";".join(it["flags"]), *[blank(it["values"][n]) for n in names]])


def print_summary(report):
    s = report["summary"]
    total = s["cell_count"]
    print("격자 %d개 (대조 %d, 다시 맞춤 %d, 구조 불일치 %d, 판독 부족 %d)" % (
        s["grid_count"], s["aligned_count"], len(s["realigned"]),
        len(s["structure_mismatch"]), len(s["insufficient_readings"])))
    print("전체 칸 %d, 확정 칸 %d" % (total, s["confirmed_count"]))
    for cat, n in s["categories"].items():
        if n:
            print("  %s: %d (%.2f%%)" % (cat, n, 100.0 * n / total if total else 0))
    conf = [(f, n) for f, n in s["flags"].items() if f.startswith("confusable:")][:5]
    if conf:
        print("혼동 쌍 상위: " + ", ".join("%s %d" % (f.split(":", 1)[1], n) for f, n in conf))
    print("판독 쌍별 다른 칸: " + ", ".join("%s %d" % kv for kv in s["pairwise_diff"].items()))
    print("재확인 대상 칸 %d (기준 격자 밖 판독 칸 %d 포함)" % (s["review_count"], s["unaligned_count"]))
    if s["structure_mismatch"]:
        print("구조 불일치 격자: " + ", ".join(s["structure_mismatch"]))
    if s["insufficient_readings"]:
        print("판독 부족 격자(판독 1벌뿐): " + ", ".join(s["insufficient_readings"]))
    for gid, names in s["excluded_readings"].items():
        print("구조를 못 맞춰 뺀 판독: %s 격자에서 %s" % (gid, ", ".join(names)))
    if s["row_shift_suspect"]:
        print("행 밀림 의심 격자: " + ", ".join(s["row_shift_suspect"]))
    if total == 0:
        print("경고: 대조한 칸이 0입니다. 판독끼리 격자 id와 구조가 맞는지 확인하세요.")
    print("주의: " + CAUTION)


def main(argv=None):
    ap = _Parser(description="독립 판독 여러 벌을 칸 단위로 대조한다.")
    ap.add_argument("--reading", action="append", default=[], metavar="이름=경로",
                    help="판독 하나(파일 또는 *.json 폴더). 2벌 이상")
    ap.add_argument("--family", action="append", default=[], metavar="이름=계열",
                    help="판독의 모델 계열. 계열이 2개 이상이면 한 계열만으로 이룬 일치를 재확인으로 돌린다")
    ap.add_argument("--out", required=True, help="보고서 JSON 경로")
    ap.add_argument("--csv", help="재확인 목록 CSV 경로(utf-8-sig)")
    try:
        args = ap.parse_args(argv)
        specs = _pairs(args.reading, "--reading")
        if len(specs) < 2:
            raise InputError("판독은 2벌 이상이어야 합니다(지금 %d벌)" % len(specs))
        families = _pairs(args.family, "--family")
        unknown = sorted(set(families) - set(specs))
        if unknown:
            raise InputError("--family에 없는 판독 이름이 있습니다: %s" % ", ".join(unknown))
        readings = {name: load_reading(path) for name, path in specs.items()}
    except InputError as e:
        print("오류: %s" % e, file=sys.stderr)
        return 1

    report = vote(readings, families or None)
    target = args.out
    try:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        if args.csv:
            target = args.csv
            pathlib.Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
            write_csv(args.csv, report)
    except OSError as e:
        print("오류: 결과 파일을 쓰지 못했습니다: %s: %s" % (target, e), file=sys.stderr)
        return 1
    print_summary(report)
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        # Windows 한국어 콘솔(cp949)에서 출력이 깨지거나 예외가 나지 않게 한다. 실행할 때만 바꾼다.
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
