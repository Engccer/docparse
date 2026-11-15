"""파서 출력(마크다운·HTML 표)을 칸별 대조용 판독 JSON으로 바꾼다 (docparse).

  python md_to_reading.py <폴더|파일...> --out <판독.json> [--suffix _upstage]

image_tables.py가 만든 표 조각(`pNNN.gXX.overview.png`)을 파서에 넣으면
`pNNN.gXX.overview_<파서>.md`가 나온다. 이 스크립트는 그 파일들에서 가장 큰 표를
골라 머리글과 본문을 가르고, cell_vote.py가 받는 꼴로 묶는다:

  {"page": "all", "grids": {"p004.g00": {"columns": 15, "header": [...], "rows": [[...]], "notes": ""}}}

- 격자 id는 파일 이름 앞머리(`p004.g00`)에서 얻는다. 그 꼴이 아닌 파일은 건너뛴다.
- `--suffix _upstage`를 주면 이름이 `_upstage.md`로 끝나는 파일만 쓴다(한 폴더에 여러 파서
  출력이 섞여 있을 때).
- 본문은 "첫 칸이 수치이거나, 비어 있지 않은 칸의 절반 이상이 수치인 첫 행"부터다. 그런 행이
  없으면(글자뿐인 표) 첫 행만 머리글로 본다. 그 위는 머리글로 보고 열마다 ` / `로 이어 붙인다.
  머리글은 대조 대상이 아니므로 파서마다 줄 수가 달라도 된다. 수치는 숫자가 든 값(12%, (1,200),
  ±0.5, △3 포함)이고, 열 번호 표시 `(1)`·`(12)`는 수치로 보지 않는다. 머리글이 4행 이상으로
  잡힌 격자는 본문이 머리글에 섞였을 수 있으므로 표준 출력에 알린다.
- HTML 표의 rowspan·colspan은 머리글에서는 같은 값을 펼쳐 채우고, 본문에서는 첫 칸에만 값을
  두고 이어지는 칸은 빈칸으로 둔다(서브에이전트 판독의 병합 칸 표기와 같게). 행마다 폭이 다르면
  빈칸으로 채우고 notes에 적는다.
- 같은 격자 id의 파일이 둘 이상 잡히면 오류다. 한 폴더에 여러 파서 출력이 있으면 `--suffix`로
  한 파서만 고른다.

값을 고치거나 추측하지 않는다. 표를 찾지 못한 파일은 출력에 넣지 않고 표준 출력에 알린다.
종료 코드: 0 = 정상, 1 = 입력 오류(맞는 파일 없음, 격자 id 중복, 표를 하나도 못 찾음). 오류면
출력 파일을 만들지 않고, 같은 경로의 이전 출력도 지운다. 표준 라이브러리만 쓴다.
"""
import argparse
import html
import json
import pathlib
import re
import sys
from html.parser import HTMLParser

GRID_ID = re.compile(r"^(p\d+\.g\d+)")
NUMERIC = re.compile(r"[\d\s./,:\-+±%()△▲▽▼~]*\d[\d\s./,:\-+±%()△▲▽▼~]*")
COLUMN_NUMBER = re.compile(r"\(\d{1,2}\)")  # 열 번호 표시 (1)·(12)는 수치가 아니다


class Cont(str):
    """rowspan·colspan으로 이어진 칸의 값(머리글에서는 값으로, 본문에서는 빈칸으로 쓴다)."""


def is_numeric(cell):
    return bool(NUMERIC.fullmatch(cell)) and not COLUMN_NUMBER.fullmatch(cell.strip())
SEPARATOR = re.compile(r"\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?")


def clean(cell):
    """칸 문자열 정리: <br>·태그·굵게 표시를 걷고 공백을 한 칸으로."""
    cell = re.sub(r"<br\s*/?>", " ", cell, flags=re.I)
    cell = html.unescape(re.sub(r"<[^>]+>", " ", cell))
    cell = cell.replace("**", "").replace("\\|", "|")
    return re.sub(r"\s+", " ", cell).strip()


class _Tables(HTMLParser):
    """HTML 표를 rowspan·colspan을 펼친 2차원 목록으로 모은다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._rows, self._row, self._cell, self._span = [], None, None, None, (1, 1)

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            a = dict(attrs)
            self._span = tuple(max(1, int(a.get(k) or 1)) if str(a.get(k) or 1).isdigit() else 1
                               for k in ("rowspan", "colspan"))
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append((clean("".join(self._cell)), *self._span))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._rows is not None:
            self.tables.append(_expand(self._rows))
            self._rows = None


def _expand(rows):
    grid, carry = [], {}  # carry: 열 번호 → (남은 행 수, 값)
    for row in rows:
        out, col, cells = [], 0, list(row)
        while cells or col in carry:
            if col in carry:
                left, value = carry[col]
                out.append(Cont(value))
                if left > 1:
                    carry[col] = (left - 1, value)
                else:
                    del carry[col]
                col += 1
                continue
            value, rs, cs = cells.pop(0)
            for k in range(cs):
                out.append(Cont(value) if k else value)
                if rs > 1:
                    carry[col] = (rs - 1, value)
                col += 1
        grid.append(out)
    return grid


def pipe_tables(text):
    """마크다운 파이프 표들. 구분선(|---|) 행은 뺀다. 빈 줄이 표를 가른다."""
    tables, cur = [], []
    for line in text.splitlines() + [""]:
        line = line.strip()
        if line.startswith("|"):
            if not SEPARATOR.fullmatch(line):
                cur.append([clean(c) for c in re.split(r"(?<!\\)\|", line.strip("|"))])
        elif cur:
            tables.append(cur)
            cur = []
    return tables


def largest_table(text):
    """문서에서 칸 수가 가장 많은 표(2차원 목록). 표가 없으면 None."""
    parser = _Tables()
    parser.feed(text)
    tables = [t for t in parser.tables + pipe_tables(text) if t]
    return max(tables, key=lambda t: sum(len(r) for r in t)) if tables else None


def _is_body(row):
    filled = [c for c in row if c]
    if not filled:
        return False
    return is_numeric(row[0]) or sum(1 for c in filled if is_numeric(c)) * 2 >= len(filled)


def to_grid(rows):
    """2차원 목록 → 판독 격자(columns·header·rows·notes)."""
    width = max(len(r) for r in rows)
    ragged = sum(1 for r in rows if len(r) != width)
    rows = [r + [""] * (width - len(r)) for r in rows]
    start = next((i for i, r in enumerate(rows) if _is_body(r)), min(1, len(rows) - 1))
    header = []
    for c in range(width):
        parts = []
        for r in rows[:start]:
            if r[c] and (not parts or parts[-1] != r[c]):
                parts.append(r[c])
        header.append(" / ".join(parts))
    notes = f"폭이 다른 행 {ragged}개를 빈칸으로 채움" if ragged else ""
    body = [["" if isinstance(c, Cont) else str(c) for c in r] for r in rows[start:]]
    return {"columns": width, "header": header, "rows": body, "notes": notes}


def grid_id(name):
    found = GRID_ID.match(pathlib.Path(name).name)
    return found.group(1) if found else None


def collect(paths, suffix):
    files = []
    for p in map(pathlib.Path, paths):
        files += sorted(p.glob("*.md")) if p.is_dir() else [p]
    end = f"{suffix}.md" if suffix else ".md"
    return [f for f in files if f.is_file() and f.name.endswith(end) and grid_id(f.name)]


def main(argv=None):
    ap = argparse.ArgumentParser(description="파서 출력의 표를 칸별 대조용 판독 JSON으로 바꾼다.")
    ap.add_argument("paths", nargs="+", help="파서 출력 .md 파일 또는 그 폴더")
    ap.add_argument("--out", required=True, help="판독 JSON 경로")
    ap.add_argument("--suffix", default="", help="이 문자열 + .md 로 끝나는 파일만 쓴다(예: _upstage)")
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out)
    files = collect(args.paths, args.suffix)

    def fail(message):
        print(f"오류: {message}")
        out.unlink(missing_ok=True)  # 이전 실행의 출력이 이번 결과로 오인되지 않게 한다
        return 1

    if not files:
        return fail("격자 id(pNNN.gXX)로 시작하는 맞는 .md 파일이 없습니다.")
    by_id = {}
    for f in files:
        by_id.setdefault(grid_id(f.name), []).append(f.name)
    clash = {g: names for g, names in by_id.items() if len(names) > 1}
    if clash:
        g, names = next(iter(clash.items()))
        return fail(f"같은 격자 id의 파일이 여러 개입니다(예: {g} = {', '.join(names)}). "
                    "--suffix로 한 파서의 출력만 고르세요.")
    grids, header_rows = {}, {}
    for f in files:
        gid = grid_id(f.name)
        rows = largest_table(f.read_text(encoding="utf-8"))
        if not rows:
            print(f"표 없음: {gid} ({f.name})")
            continue
        grids[gid] = to_grid(rows)
        header_rows[gid] = len(rows) - len(grids[gid]["rows"])
    if not grids:
        return fail("어느 파일에서도 표를 찾지 못했습니다.")
    out.write_text(json.dumps({"page": "all", "grids": grids}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"격자 {len(grids)}개를 {args.out}에 썼습니다.")
    bodyless = [g for g, v in grids.items() if not v["rows"]]
    if bodyless:
        print(f"본문 행이 없는 격자: {', '.join(bodyless)}")
    tall = [f"{g}({n}행)" for g, n in header_rows.items() if n >= 4 and g not in bodyless]
    if tall:
        print(f"머리글이 4행 이상으로 잡힌 격자(본문이 머리글에 섞였는지 확인): {', '.join(tall)}")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        # Windows 한국어 콘솔(cp949)에서 출력이 깨지거나 예외가 나지 않게 한다. 실행할 때만 바꾼다.
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
