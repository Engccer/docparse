"""괘선 표 PDF 결정론 파서 (docparse Tier 0): pdfplumber로 외부 API 없이 추출.

다른 *_parse.py와 동일한 인터페이스:
  python pdfplumber_parse.py "<파일.pdf>"        → <파일>_pdfplumber.md

대상(좁고 깊은 대역): 벡터 괘선으로 그려진 정형 표 + 텍스트 레이어가 있는 PDF
(시간표·명렬표·집계표·주간학습안내 등 행정 문서). assess_document.py가
table_hint: true + has_text_layer: true로 진단한 문서에서 최우선 시도한다.
무료·로컬·비-LLM이라 환각·무단교정이 구조적으로 없고, 빈 셀이 빈 문자열로
보존된다(칸이 비어 있다는 사실 자체가 정보인 문서 유형에 중요).

자가검증 내장: extract_tables()(격자 모델)와 extract_words()(좌표 모델)는 같은
PDF에 대한 서로 독립적인 두 관점이다. 단어 중심 좌표를 셀 bbox에 재배치해 격자
추출 결과와 셀 단위 양방향 대조하므로, 격자 모델이 값을 옆 열로 밀어 넣으면
반드시 불일치로 드러난다(단순 개수 대조와 달리 열 배정 오류를 잡는다). 병합
셀(None 셀)은 괘선 전략에서 칸 경계 좌표로 범위를 복원할 수 있으면 rowspan·colspan
HTML 표로 내고, 복원할 수 없으면(또는 text 전략이면) 경고 대상이다. 경고가 하나라도
있으면 출력 파일을 만들지 않는다 — 기존 티어(LlamaParse v2·Upstage 등)로 승격할 것.

괘선 전략이 실패하면 2차원 무늬를 이루는 작은 채움 도형(선 없이 채움만 있고 가로·세로가
모두 3pt 이상 15pt 미만이며, 좌우와 위아래 양쪽에 같은 크기의 이웃이 있는 것)을 두 엔진에서
빼고 한 번 더 시도한다. 쪽 여백의 장식 무늬가 쪽 전체를 덮는 가짜 격자로 잡히는 문서가
있어서다. 한 방향으로만 이어진 도형은 굵은 점선 칸막이일 수 있어 빼지 않는다. 뺀 무늬가 주로
재시도 표 안에 있거나(쪽 장식은 표 밖으로 이어진다), 뺀 도형이 한 칸 안에서 낱말과 낱말
사이에 놓였으면 그 재시도는 쓰지 않는다. 회전된 쪽은 회전을 푼 사본으로 PyMuPDF 교차 대조를
한다(회전 쪽에서 PyMuPDF가 낱말을 자르는 문제 회피). 낱말 상자가 행 경계선에 닿아 두 엔진의 위아래 칸
배정만 갈린 경우는 실패로 치지 않고 출력 맨 위 주석으로 알린다.

PDF 추출 구현 간 교차 대조: 위 두 관점은 모두 pdfplumber 내부라,
열 경계 오인처럼 격자·좌표가 같은 상류 결함을 공유하는 오류는 잡지 못한다.
PyMuPDF find_tables()로 같은 표를 다시 추출해 표 개수·구조(행x열)·셀 내용을
대조한다(crosscheck_with_fitz). PDF 텍스트·벡터 추출 구현은 다르지만,
표 탐지 알고리즘에는 pdfplumber 포팅이라는 공통 계보가 있다.
두 결과가 일치해야만 PASS다. PyMuPDF는 필수 의존성이다(2026-08-31): 종전에는
미설치 시 교차 투표를 생략하고도 PASS를 냈는데, 그 PASS는 단일 엔진 자가검증만
통과한 것이라 이 티어가 약속하는 "PDF 추출 구현 간 일치"가 아니다. 미설치면 출력을
만들지 않고 설치를 안내한다(assess_document.py도 같은 패키지를 요구한다).

종료 코드: 0 = PASS(출력 파일 생성), 1 = 오류·경고(출력 없음). 실행 시작 시
같은 이름의 이전 출력을 지워, 실패한 실행 뒤에 옛 파일이 남지 않게 한다.

--strategy text (opt-in, 2026-08-11 추가): 괘선 없는 정렬 표는 단어 좌표
정렬로 열을 추정한다(pdfplumber text 전략). 이때 격자·좌표 두 관점이 같은
단어 좌표에서 나와 자가검증의 독립성이 약해지므로, PyMuPDF text 전략과의
교차 투표가 필수 게이트다. 열 경계가 단어를 관통해 쪼개는 오탐(산문을 표로
오인)은 단어↔셀 대조가 잡는다(실측: 산문 PDF에서 두 엔진이 같은 43x14
쓰레기 표에 수렴했지만 단어 분절 불일치로 거부됨). 주의: 괘선이 없으면 열
구획 정보가 문서에 존재하지 않으므로, PASS는 "단어 보존 + 2엔진 구조 수렴"
이지 열 구획이 시각 의도와 일치한다는 보장은 아니다. 렌더링 시 데이터 없는
빈 간격 행(줄간격 추정 부산물)은 제거한다.

한계: 스캔본(텍스트 레이어 없음)은 출력 0(OCR 기능 없음), 병합·rowspan 셀은
격자 모델이 깨짐, 다단 산문·헤딩 위계는 범위 밖. 해당 문서는 기존 티어
파이프라인을 그대로 쓴다.
"""
import html
import io
import os
import sys
import traceback

SUPPORTED_EXTENSIONS = [".pdf"]
MAX_PROBLEM_SAMPLES = 10  # 경고 출력 시 예시 상한
SPAN_TOLERANCE_PT = 1  # 병합 칸이 다음 행·열 경계를 넘는지 볼 때의 여유(pt)
# 재시도 때 격자 후보에서 빼는 장식 도형: 선 없이 채움만 있고, 가로·세로가 모두 DECOR_MIN_PT 이상
# DECOR_MAX_PT 미만이며, 2차원 무늬를 이루는 것(실측: 쪽 여백의 6pt 체크무늬. 표 가장자리 칸에 조금
# 걸친다). 2차원 무늬는 크기가 같은 도형이 좌우와 위아래 양쪽에 DECOR_MAX_PT 이하 간격으로 함께
# 있는 것이다. 한 방향으로만 이어진 줄(굵은 점선 칸막이)과 외톨이 도형은 빼지 않는다. 뺀 무늬가
# 주로 표 안에 있으면(_decor_inside_tables) 재시도를 버린다.
DECOR_MIN_PT = 3
DECOR_MAX_PT = 15


def get_output_filename(input_file):
    """입력 파일 경로 기반 출력 경로(<base>_pdfplumber.md) 생성."""
    dir_path = os.path.dirname(input_file)
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_name = f"{base_name}_pdfplumber.md"
    return os.path.join(dir_path, output_name) if dir_path else output_name


def clear_stale_output(output_file):
    """같은 이름의 이전 출력이 있으면 지운다(실패한 실행 뒤 옛 파일 잔존 방지)."""
    if os.path.exists(output_file):
        os.remove(output_file)
        print(f"기존 출력 제거: {output_file}")


def _cell_md(value):
    """셀 텍스트를 마크다운 표 셀로: 내부 개행·연속 공백은 한 칸으로, 파이프 이스케이프."""
    if value is None:
        return ""
    return " ".join(value.split()).replace("|", "\\|")


def _grid_to_markdown(grid, drop_empty_rows=False):
    """extract_tables() 격자를 마크다운 표로. 빈 셀은 빈 칸으로 보존.

    drop_empty_rows: text 전략 전용. 줄간격 추정이 만드는 데이터 없는 간격
    행만 제거한다(괘선 표의 빈 행은 양식 정보이므로 lines 전략에선 보존).
    """
    if drop_empty_rows:
        grid = [row for row in grid if any(v and str(v).strip() for v in row)]
    if not grid:
        return ""
    width = max(len(row) for row in grid)
    lines = []
    for i, row in enumerate(grid):
        cells = [_cell_md(v) for v in row] + [""] * (width - len(row))
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("|" + " --- |" * width)
    return "\n".join(lines)


def table_spans(table):
    """병합 칸의 범위를 칸 bbox에서 복원한다: {(r, c): (rowspan, colspan)}.

    격자 모델에서 병합 칸은 왼쪽 위 자리에만 있고 나머지 자리는 None이다. 칸의 오른쪽·
    아래 경계가 몇 개의 열·행 시작선을 넘는지로 범위를 되찾는다. None 자리가 병합 칸
    하나로 정확히 설명되지 않으면(표가 깨진 것) None을 돌려준다.
    """
    rows = table.rows
    width = max((len(row.cells) for row in rows), default=0)
    tops = [row.bbox[1] for row in rows]
    lefts = [None] * width
    for row in rows:
        for c, cell in enumerate(row.cells):
            if cell is not None and (lefts[c] is None or cell[0] < lefts[c]):
                lefts[c] = cell[0]
    if any(x is None for x in lefts):
        return None
    spans = {}
    covered = {}
    for r, row in enumerate(rows):
        for c, cell in enumerate(row.cells):
            if cell is None:
                continue
            colspan = sum(1 for j in range(c, width) if lefts[j] < cell[2] - SPAN_TOLERANCE_PT)
            rowspan = sum(1 for i in range(r, len(rows)) if tops[i] < cell[3] - SPAN_TOLERANCE_PT)
            for i in range(r, r + rowspan):
                for j in range(c, c + colspan):
                    if (i, j) in covered:
                        return None
                    covered[(i, j)] = (r, c)
            if rowspan > 1 or colspan > 1:
                spans[(r, c)] = (rowspan, colspan)
    for r, row in enumerate(rows):
        for c in range(width):
            cell = row.cells[c] if c < len(row.cells) else None
            if cell is None and (r, c) not in covered:
                return None
    return spans


def _grid_to_html(grid, spans):
    """병합 칸이 있는 표를 rowspan·colspan이 살아 있는 HTML 표로."""
    hidden = set()
    for (r, c), (rowspan, colspan) in spans.items():
        hidden.update(
            (i, j) for i in range(r, r + rowspan) for j in range(c, c + colspan) if (i, j) != (r, c)
        )
    lines = ["<table>"]
    for r, row in enumerate(grid):
        cells = []
        for c, value in enumerate(row):
            if (r, c) in hidden:
                continue
            rowspan, colspan = spans.get((r, c), (1, 1))
            attrs = (f' rowspan="{rowspan}"' if rowspan > 1 else "") + (
                f' colspan="{colspan}"' if colspan > 1 else ""
            )
            cells.append(f"<td{attrs}>{html.escape(' '.join((value or '').split()))}</td>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _unrotated_bytes(filename):
    """/Rotate가 걸린 쪽이 있으면 회전을 푼 사본(bytes), 없으면 None.

    회전된 쪽은 pdfplumber와 PyMuPDF의 좌표계가 달라져 교차 대조가 성립하지 않는다
    (실측: 90도 쪽에서 PyMuPDF가 낱말을 열 경계로 잘랐다). 두 엔진이 같은 사본을 읽게 한다.
    """
    try:
        import fitz
    except ImportError:
        return None
    with fitz.open(filename) as doc:
        if not any(page.rotation for page in doc):
            return None
        for page in doc:
            page.remove_rotation()
        return doc.tobytes()


def _in_bbox(cx, cy, bbox):
    x0, top, x1, bottom = bbox
    return x0 <= cx <= x1 and top <= cy <= bottom


def _assign_words_to_cells(page, tables):
    """extract_words() 좌표를 셀 bbox에 재배치 — 격자 추출과 독립적인 관점.

    반환: ((ti, r, c) -> 토큰 리스트, 표 bbox 안이지만 어느 셀에도 못 들어간 단어들)
    """
    assignments = {}
    unassigned = []
    for w in page.extract_words():
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        target = None
        for ti, table in enumerate(tables):
            if _in_bbox(cx, cy, table.bbox):
                target = ti
                break
        if target is None:
            continue  # 표 밖 텍스트(제목·산문)는 검증 대상이 아니다
        placed = False
        for r, row in enumerate(tables[target].rows):
            for c, cell in enumerate(row.cells):
                if cell is not None and _in_bbox(cx, cy, cell):
                    assignments.setdefault((target, r, c), []).append(w["text"])
                    placed = True
                    break
            if placed:
                break
        if not placed:
            unassigned.append(w["text"])
    return assignments, unassigned


def verify_page(grids, assignments):
    """격자 추출(view A) vs 좌표 재배치(view B)를 셀 단위 양방향 대조.

    반환: (대조한 셀 수, 불일치 목록[(ti, r, c, viewA, viewB)])
    """
    problems = []
    checked = 0
    remaining = dict(assignments)
    for ti, grid in enumerate(grids):
        for r, row in enumerate(grid):
            for c, value in enumerate(row):
                checked += 1
                a_tokens = sorted((value or "").split())
                b_tokens = sorted(remaining.pop((ti, r, c), []))
                if a_tokens != b_tokens:
                    problems.append((ti, r, c, " ".join(a_tokens), " ".join(b_tokens)))
    # 격자에 없는 좌표 배정이 남았다면(이론상 없어야 함) 그것도 불일치다
    for (ti, r, c), tokens in remaining.items():
        problems.append((ti, r, c, "", " ".join(sorted(tokens))))
    return checked, problems


def _bbox_overlap_ratio(a, b):
    """두 bbox의 교집합 넓이 / 작은 쪽 넓이 (0.0~1.0). 표 짝짓기용."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return (ix * iy) / smaller if smaller > 0 else 0.0


def _is_decor(width, height, fill, stroke):
    """격자 후보에서 뺄 장식 도형인가: 선 없이 채움만 있고 가로·세로가 모두 작되 가늘지 않다.

    가는 도형(한쪽이 DECOR_MIN_PT 미만)은 칸마다 끊어 그린 괘선일 수 있어 빼지 않는다.
    """
    return bool(fill) and not stroke and DECOR_MIN_PT <= min(width, height) and max(width, height) < DECOR_MAX_PT


def _lattice(boxes):
    """상자 (x0, top, x1, bottom) 목록에서 2차원 무늬들을 찾는다: 무늬마다 상자 번호 집합 하나.

    크기가 같은(가로·세로 1pt 이내) 상자가 같은 세로줄의 위아래에, 그리고 같은 가로줄의
    좌우에 DECOR_MAX_PT 이하 간격으로 모두 있어야 무늬에 든다. 한 방향으로만 이웃이 있으면
    줄이다. 이웃 관계로 이어진 상자들이 한 무늬다.
    """
    sides, pairs = [], []
    for lo, hi, a, b in ((0, 2, 1, 3), (1, 3, 0, 2)):  # 위아래 이웃, 좌우 이웃
        found = set()
        order = sorted(range(len(boxes)), key=lambda i: boxes[i][lo])
        for n, i in enumerate(order):
            for k in order[n + 1:]:
                if boxes[k][lo] - boxes[i][lo] > 1:
                    break
                if abs(boxes[k][hi] - boxes[i][hi]) > 1:
                    continue
                if abs((boxes[k][b] - boxes[k][a]) - (boxes[i][b] - boxes[i][a])) > 1:
                    continue  # 크기가 다른 도형(무늬 옆에 놓인 점선의 대시)은 이웃이 아니다
                gap = max(boxes[i][a], boxes[k][a]) - min(boxes[i][b], boxes[k][b])
                if gap <= DECOR_MAX_PT:
                    found.update((i, k))
                    pairs.append((i, k))
        sides.append(found)
    members = sides[0] & sides[1]
    root = {i: i for i in members}

    def find(i):
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    for i, k in pairs:
        if i in members and k in members:
            root[find(i)] = find(k)
    groups = {}
    for i in members:
        groups.setdefault(find(i), set()).add(i)
    return list(groups.values())


def _decor_groups(shapes):
    """(상자, 채움, 선) 목록에서 장식 무늬들: _is_decor에 들고 2차원 무늬를 이루는 도형의 번호 집합 목록."""
    candidates = [i for i, (box, fill, stroke) in enumerate(shapes)
                  if _is_decor(box[2] - box[0], box[3] - box[1], fill, stroke)]
    return [{candidates[n] for n in group} for group in _lattice([shapes[i][0] for i in candidates])]


def _decor_boxes(shapes):
    """(상자, 채움, 선) 목록에서 장식 도형의 번호 집합."""
    return set().union(*_decor_groups(shapes))


def _without_decor(page):
    """장식 도형을 뺀 pdfplumber 쪽(표 탐지용)과 뺀 무늬들(무늬마다 상자 목록). 글자는 그대로다."""
    objects = page.rects + page.curves
    shapes = [((o["x0"], o["top"], o["x1"], o["bottom"]), o.get("fill"), o.get("stroke")) for o in objects]
    groups = [sorted({shapes[i][0] for i in group}) for group in _decor_groups(shapes)]
    boxes = {box for group in groups for box in group}
    kinds = ("rect", "curve")
    return (page.filter(lambda o: not (o.get("object_type") in kinds
                                       and (o["x0"], o["top"], o["x1"], o["bottom"]) in boxes)),
            groups)


def _decor_inside_tables(tables, groups):
    """뺀 무늬 가운데 도형의 절반 넘게가 표 안에 있는 것의 수.

    쪽 장식은 표 밖으로 이어지고(실측: 도형의 3%만 표에 걸침), 표 안에만 있는 무늬는 표의
    일부(나란한 점선 칸막이 등)일 수 있다.
    """
    def in_table(box):
        return any(min(box[2], t.bbox[2]) > max(box[0], t.bbox[0])
                   and min(box[3], t.bbox[3]) > max(box[1], t.bbox[1]) for t in tables)

    return sum(1 for group in groups if sum(map(in_table, group)) * 2 > len(group))


def _decor_between_words(page, tables, boxes):
    """뺀 도형 가운데, 표의 한 칸 안에서 낱말과 낱말 사이(좌우 또는 위아래)에 놓인 것의 수.

    그런 도형은 두 칸을 가르던 칸막이였을 수 있다. 빼면 두 엔진이 똑같이 칸을 합치므로
    교차 대조로는 드러나지 않는다.
    """
    if not boxes:
        return 0
    words = page.extract_words()
    count = 0
    for table in tables:
        inside = [b for b in boxes if min(b[2], table.bbox[2]) > max(b[0], table.bbox[0])
                  and min(b[3], table.bbox[3]) > max(b[1], table.bbox[1])]
        if not inside:
            continue
        for row in table.rows:
            for cell in row.cells:
                if cell is None:
                    continue
                mine = [w for w in words
                        if _in_bbox((w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2, cell)]
                if len(mine) < 2:
                    continue
                for x0, top, x1, bottom in inside:
                    if not (min(x1, cell[2]) > max(x0, cell[0]) and min(bottom, cell[3]) > max(top, cell[1])):
                        continue
                    # "사이"는 같은 줄의 좌우 낱말 틈, 또는 같은 세로 띠의 위아래 낱말 틈이다.
                    # 낱말들 옆으로 비켜난 도형(칸 가장자리에 걸친 여백 무늬)과 낱말에 겹친
                    # 도형(글자 뒤에 깔린 무늬)은 세지 않는다.
                    if any(w["x0"] < x1 and w["x1"] > x0 and w["top"] < bottom and w["bottom"] > top
                           for w in mine):
                        continue
                    mid_x, mid_y = (x0 + x1) / 2, (top + bottom) / 2
                    level = [w for w in mine if w["top"] < bottom and w["bottom"] > top]
                    column = [w for w in mine if w["x0"] < x1 and w["x1"] > x0]
                    sideways = any(w["x1"] <= mid_x for w in level) and any(w["x0"] >= mid_x for w in level)
                    stacked = any(w["bottom"] <= mid_y for w in column) and any(w["top"] >= mid_y for w in column)
                    count += sideways or stacked
    return count


def _fitz_page_tables(filename, strategy="lines", drop_decor=False, stream=None):
    """PyMuPDF find_tables로 페이지별 [(bbox, grid)] 추출. 미가용이면 None.

    drop_decor면 장식 도형(_decor_boxes: 채움만 있는 작은 경로 가운데 2차원 무늬를 이루는 것,
    경로 전체 상자 기준)을 뺀 벡터 경로만 넘긴다. pdfplumber 쪽에도 같은 기준을 건다.

    fitz.table 첫 사용 시 pymupdf_layout 권유 안내문이 stdout으로 나오므로,
    파서 출력 오염을 막기 위해 fitz 구간만 캡처한다.
    """
    try:
        import fitz
    except ImportError:
        return None
    if not hasattr(getattr(fitz, "Page", None), "find_tables"):
        return None
    import contextlib
    import inspect
    import io

    options = {"strategy": strategy}
    finder = getattr(getattr(fitz, "table", None), "find_tables", None)
    if finder is not None and "use_layout" in inspect.signature(finder).parameters:
        # layout 모델 유무와 무관하게 기존 괘선·텍스트 기반 대조를 유지한다.
        options["use_layout"] = False
    if drop_decor and (finder is None or "paths" not in inspect.signature(finder).parameters):
        raise RuntimeError("설치된 PyMuPDF의 find_tables가 paths 인자를 지원하지 않습니다")

    pages = []
    with contextlib.redirect_stdout(io.StringIO()):
        with (fitz.open(stream=stream, filetype="pdf") if stream else fitz.open(filename)) as doc:
            for page in doc:
                # CropBox != MediaBox면 fitz는 cropbox 원점 기준, pdfplumber는
                # mediabox 기준 좌표를 내므로 mediabox 기준으로 평행이동한다.
                dx = page.cropbox.x0 - page.mediabox.x0
                dy = page.mediabox.y1 - page.cropbox.y1
                if drop_decor:
                    drawings = page.get_drawings()
                    decor = _decor_boxes([(tuple(d["rect"]), d.get("type") == "f", False) for d in drawings])
                    options["paths"] = [d for i, d in enumerate(drawings) if i not in decor]
                pages.append([
                    ((t.bbox[0] + dx, t.bbox[1] + dy, t.bbox[2] + dx, t.bbox[3] + dy),
                     t.extract())
                    for t in page.find_tables(**options).tables
                ])
    return pages


def _split_only(a, b):
    """두 낱말 목록이 낱말을 끊는 자리만 다른가("AB_CD" 대 "AB", "_", "CD").

    글자 구성이 같고, 더 잘게 끊긴 쪽의 낱말이 모두 다른 쪽 어느 낱말의 일부여야 한다.
    숫자가 든 낱말은 두 쪽에 똑같이 있어야 한다(51 대 "5 1", 1/2 대 "2 / 1"은 다른 값).
    글자 순서가 바뀐 값(1,250 대 1,520)은 여기 들지 않는다.
    """
    def numeric(tokens):
        return sorted(t for t in tokens if any(ch.isdigit() for ch in t))

    if sorted("".join(a)) != sorted("".join(b)) or numeric(a) != numeric(b):
        return False
    fine, coarse = (a, b) if len(a) >= len(b) else (b, a)
    return all(any(t in u for u in coarse) for t in fine)


def _boundary_words(page, tables):
    """낱말 상자가 아래 행과의 경계선을 가로지르는 칸 {(표, 행, 열)} (행은 경계선 위쪽 행).

    경계선은 아래 행의 윗변이다(행 상자의 아랫변은 세로 병합 칸 때문에 더 아래일 수 있다).
    """
    found = set()
    for w in page.extract_words():
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        for ti, table in enumerate(tables):
            if not _in_bbox(cx, cy, table.bbox):
                continue
            rows = table.rows
            for r in range(len(rows) - 1):
                line = rows[r + 1].bbox[1]
                if not w["top"] < line < w["bottom"]:
                    continue
                for row in (rows[r], rows[r + 1]):
                    for c, cell in enumerate(row.cells):
                        if cell is not None and cell[0] <= cx <= cell[2]:
                            found.add((ti, r, c))
            break
    return found


def crosscheck_with_fitz(filename, pages_tables, strategy="lines", drop_decor=False, stream=None,
                         boundary_words=None):
    """pdfplumber 격자를 PyMuPDF의 PDF 추출 결과와 셀 단위로 대조.

    verify_page(격자↔좌표)는 pdfplumber 내부의 두 관점이라, 두 관점이 같은
    상류 결함(열 경계 오인 등)을 공유하면 통과해 버린다. 다른 PDF 텍스트·벡터
    추출 구현의 결과와 대조하되 표 탐지 알고리즘의 공통 계보까지 제거하지는 못한다.

    글자가 위아래 두 칸의 경계선에 걸치면 두 구현의 배정이 갈릴 수 있다. 같은 열의
    이웃한 두 행에서 한 구현은 위 칸에, 다른 구현은 아래 칸에 같은 내용을 두고 나머지
    칸은 비어 있으며, 그 경계선에 실제로 낱말 상자가 닿아 있을 때만(boundary_words)
    불일치로 세지 않고 걸친 자리로 따로 돌려준다. 한 칸은 한 번만 짝짓는다.

    pages_tables: 페이지별 [(bbox, grid), ...] (pdfplumber 추출 결과)
    boundary_words: 페이지별 {(표, 행, 열)} (_boundary_words). 없으면 걸친 자리를 인정하지 않는다.
    반환: (대조 셀 수, 문제 목록[str], 경계에 걸친 자리 목록[str]) 또는 None(PyMuPDF 미가용)
    """
    try:
        fitz_pages = _fitz_page_tables(filename, strategy, drop_decor, stream)
    except Exception as e:
        # fitz가 문서 열기·표 추출에서 죽으면 그 자체를 불일치로 간주(fail-closed)
        return 0, [f"PyMuPDF 실행 오류(교차 투표 실패로 간주): {e}"], []
    if fitz_pages is None:
        return None

    checked = 0
    problems = []
    straddles = []
    if len(pages_tables) != len(fitz_pages):
        # zip이 짧은 쪽에서 멈춰 초과 페이지의 표가 검증을 탈출하는 것을 막는다
        problems.append(
            f"페이지 수 불일치: pdfplumber {len(pages_tables)}p / fitz {len(fitz_pages)}p"
        )
    for page_no, (p_tables, f_tables) in enumerate(zip(pages_tables, fitz_pages), start=1):
        if len(p_tables) != len(f_tables):
            problems.append(
                f"p{page_no}: 표 개수 불일치 pdfplumber {len(p_tables)}개 / fitz {len(f_tables)}개"
            )
        remaining = list(f_tables)
        for ti, (bbox, grid) in enumerate(p_tables):
            match_idx = None
            for j, (f_bbox, _) in enumerate(remaining):
                if _bbox_overlap_ratio(bbox, f_bbox) >= 0.5:
                    match_idx = j
                    break
            if match_idx is None:
                problems.append(f"p{page_no} 표{ti + 1}: fitz에서 대응하는 표를 찾지 못함")
                continue
            _, f_grid = remaining.pop(match_idx)
            p_rows = len(grid)
            p_cols = max((len(r) for r in grid), default=0)
            f_rows = len(f_grid)
            f_cols = max((len(r) for r in f_grid), default=0)
            if (p_rows, p_cols) != (f_rows, f_cols):
                problems.append(
                    f"p{page_no} 표{ti + 1}: 구조 불일치 pdfplumber {p_rows}x{p_cols} / fitz {f_rows}x{f_cols}"
                )
                continue
            merged = any(v is None for g in (grid, f_grid) for row in g for v in row)
            diffs = {}
            for r in range(p_rows):
                for c in range(p_cols):
                    checked += 1
                    a_raw = grid[r][c] if c < len(grid[r]) else ""
                    b_raw = f_grid[r][c] if c < len(f_grid[r]) else ""
                    if merged and (a_raw is None) != (b_raw is None):
                        # 병합 칸을 살려 내보내는 표는 두 엔진이 같은 자리를 병합으로 봐야 한다
                        problems.append(f"p{page_no} 표{ti + 1} ({r},{c}): 병합 자리 불일치")
                        continue
                    a = sorted((a_raw or "").split())
                    b = sorted((b_raw or "").split())
                    if a != b and not _split_only(a, b):
                        diffs[(r, c)] = (a, b)
            touching = boundary_words[page_no - 1] if boundary_words else set()
            paired = set()
            for (r, c), (a, b) in sorted(diffs.items()):
                if (r, c) in paired:
                    continue  # 위 칸과 이미 짝지어 걸친 자리로 기록했다
                below = diffs.get((r + 1, c))
                if (below and (r + 1, c) not in paired and not (a and b)
                        and (a, b) == (below[1], below[0]) and (ti, r, c) in touching):
                    paired.update({(r, c), (r + 1, c)})
                    straddles.append(f"p{page_no} 표{ti + 1} ({r},{c})~({r + 1},{c}): '{' '.join(a or b)}'")
                else:
                    problems.append(
                        f"p{page_no} 표{ti + 1} ({r},{c}): "
                        f"pdfplumber='{' '.join(a)}' / fitz='{' '.join(b)}'"
                    )
    return checked, problems, straddles


def _page_body(page, tables, grids, drop_empty_rows=False, spans=None):
    """페이지 본문 구성: 표 밖 텍스트 라인과 표를 상단 좌표순으로 배치.

    표 밖 텍스트를 통째로 앞에 몰면 표 사이·아래의 캡션이 첫 표보다 앞에 와
    읽기 순서가 왜곡되므로, 라인·표를 top 좌표로 정렬해 원문 순서를 보존한다.
    """
    bboxes = [t.bbox for t in tables]
    items = []
    for line in page.extract_text_lines():
        cx = (line["x0"] + line["x1"]) / 2
        cy = (line["top"] + line["bottom"]) / 2
        if any(_in_bbox(cx, cy, b) for b in bboxes):
            continue
        text = line["text"].strip()
        if text:
            items.append((line["top"], "text", text))
    for ti, (table, grid) in enumerate(zip(tables, grids)):
        if spans and spans[ti]:
            md = _grid_to_html(grid, spans[ti])
        else:
            md = _grid_to_markdown(grid, drop_empty_rows=drop_empty_rows)
        if md:
            items.append((table.bbox[1], "table", md))
    items.sort(key=lambda it: it[0])

    parts = []
    for _, kind, content in items:
        if kind == "text" and parts and parts[-1][0] == "text":
            parts[-1] = ("text", parts[-1][1] + "\n" + content)
        else:
            parts.append((kind, content))
    return [content for _, content in parts]


def _attempt(filename, strategy, drop_decor=False, stream=None):
    """한 설정으로 추출·자가검증·교차 대조를 돌린다. 표가 없으면 None.

    drop_decor: 작은 채움 도형(_is_decor)을 격자 후보에서 뺀다(lines 전략 재시도용).
        뺀 도형이 한 칸 안의 낱말 사이에 놓였으면 ok가 아니다.
    stream: 회전을 푼 사본(bytes). 있으면 두 엔진 모두 이것을 읽는다.
    """
    import pdfplumber

    if strategy == "text":
        table_settings = {"vertical_strategy": "text", "horizontal_strategy": "text"}
    else:
        table_settings = None
    sections = []
    total_tables = 0
    total_cells = 0
    total_nonempty = 0
    total_checked = 0
    merged_cells = 0
    restored_spans = 0
    decor_in_tables = 0  # 재시도에서 뺀 도형 가운데 한 칸 안의 낱말 사이에 놓인 것(있으면 재시도 무효)
    decor_patterns = 0   # 재시도에서 뺀 무늬 가운데 주로 표 안에 있는 것(있으면 재시도 무효)
    all_problems = []
    all_unassigned = []
    pages_tables = []  # 교차 투표용: 페이지별 [(bbox, grid), ...]
    boundary_words = []  # 페이지별: 낱말이 행 경계선에 닿은 칸

    with pdfplumber.open(io.BytesIO(stream) if stream else filename) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            finder_page, decor = _without_decor(page) if drop_decor else (page, [])
            tables = finder_page.find_tables(table_settings)
            decor_in_tables += _decor_between_words(page, tables, [box for group in decor for box in group])
            decor_patterns += _decor_inside_tables(tables, decor)
            grids = [t.extract() for t in tables]
            spans = []
            for table in tables:
                # 병합(colspan/rowspan) 칸은 None 자리로 나타난다. 괘선 표에서 범위를
                # 칸 bbox로 되찾을 수 있으면 HTML 표로 살려 내보내고, 못 찾으면 경고한다.
                none_cells = sum(1 for row in table.rows for cell in row.cells if cell is None)
                found = table_spans(table) if none_cells and strategy == "lines" else None
                spans.append(found)
                if found:
                    restored_spans += len(found)
                else:
                    merged_cells += none_cells
            for grid in grids:
                for row in grid:
                    total_cells += len(row)
                    total_nonempty += sum(1 for v in row if v and v.strip())
            total_tables += len(tables)
            pages_tables.append([(t.bbox, g) for t, g in zip(tables, grids)])
            boundary_words.append(_boundary_words(page, tables))

            body = _page_body(page, tables, grids, drop_empty_rows=(strategy == "text"), spans=spans)
            if page_count > 1:
                body.insert(0, f"## 페이지 {i}")
            sections.append("\n\n".join(body))

            assignments, unassigned = _assign_words_to_cells(page, tables)
            checked, problems = verify_page(grids, assignments)
            total_checked += checked
            all_problems.extend((i, *p) for p in problems)
            all_unassigned.extend((i, t) for t in unassigned)

    if total_tables == 0:
        return None

    print(f"페이지 {page_count} · 표 {total_tables}개 · 셀 {total_cells}개(내용 있는 셀 {total_nonempty})")
    print(f"자가검증(격자 추출 ↔ 좌표 재배치 양방향 대조): 셀 {total_checked}건")

    if restored_spans:
        print(f"병합 칸 {restored_spans}개의 범위를 복원했습니다(해당 표는 HTML 표로 출력).")

    cross = crosscheck_with_fitz(filename, pages_tables, strategy, drop_decor, stream, boundary_words)
    if cross is None:
        return {"cross": None}
    cross_checked, cross_problems, straddles = cross
    print(f"교차 대조(pdfplumber / PyMuPDF find_tables): 셀 {cross_checked}건 대조")
    if straddles:
        print(f"경계선에 걸친 글자 {len(straddles)}곳: 값은 두 구현이 같고 위아래 어느 칸인지만 갈립니다(pdfplumber 배정을 따름).")
        for line in straddles[:MAX_PROBLEM_SAMPLES]:
            print(f"  - {line}")

    ok = not (all_problems or all_unassigned or merged_cells or cross_problems or decor_in_tables
              or decor_patterns)
    if decor_patterns:
        print(f"경고: 뺀 무늬 {decor_patterns}개가 주로 표 안에 있습니다. 표의 칸막이일 수 있어 이 재시도를 쓰지 않습니다.")
    if decor_in_tables:
        print(f"경고: 뺀 도형 {decor_in_tables}개가 한 칸 안의 낱말 사이에 있습니다. 칸막이였을 수 있어 이 재시도를 쓰지 않습니다.")
    if not ok:
        print(
            f"경고: 셀 불일치 {len(all_problems)}건 · 미배정 단어 {len(all_unassigned)}건"
            f" · 병합 의심 셀 {merged_cells}건 · 교차 엔진 불일치 {len(cross_problems)}건"
        )
        for page_no, ti, r, c, a, b in all_problems[:MAX_PROBLEM_SAMPLES]:
            print(f"  - p{page_no} 표{ti + 1} ({r},{c}): 격자='{a}' / 좌표='{b}'")
        if len(all_problems) > MAX_PROBLEM_SAMPLES:
            print(f"  ... 외 {len(all_problems) - MAX_PROBLEM_SAMPLES}건")
        if all_unassigned:
            samples = ", ".join(t for _, t in all_unassigned[:MAX_PROBLEM_SAMPLES])
            print(f"  - 미배정(병합 셀·경계 걸침 의심): {samples}")
        if merged_cells:
            print("  - 범위를 복원하지 못한 병합 셀은 span 정보가 소실됩니다")
        for line in cross_problems[:MAX_PROBLEM_SAMPLES]:
            print(f"  - [교차] {line}")
        if len(cross_problems) > MAX_PROBLEM_SAMPLES:
            print(f"  ... 외 [교차] {len(cross_problems) - MAX_PROBLEM_SAMPLES}건")
    return {"cross": cross, "ok": ok, "sections": sections, "straddles": straddles}


def process_file(filename, strategy="lines"):
    """PASS로 출력 파일을 만들었으면 True."""
    print(f"입력 파일: {filename}")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
        print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
        return False
    if not os.path.exists(filename):
        print(f"오류: 파일을 찾을 수 없습니다: {filename}")
        return False

    output_file = get_output_filename(filename)
    clear_stale_output(output_file)

    if strategy == "text":
        print("추출 중... (pdfplumber text 전략: 괘선 없는 정렬 표 + 좌표 재배치 자가검증)")
    else:
        print("추출 중... (pdfplumber 격자 모델 + 좌표 재배치 자가검증)")

    stream = _unrotated_bytes(filename)
    if stream:
        print("회전된 쪽이 있어 회전을 푼 사본으로 추출합니다(원본 파일은 그대로).")

    result = _attempt(filename, strategy, stream=stream)
    if result is None:
        if strategy == "text":
            print("경고: text 전략으로도 정렬 표를 찾지 못했습니다. 이 문서는 Tier 0 대상이 아닙니다.")
            print("→ 스캔본이거나 표가 없는 문서일 수 있습니다. 기존 티어(assess_document.py 추천)를 쓰세요.")
        else:
            print("경고: 괘선 표를 하나도 찾지 못했습니다. 이 문서는 Tier 0 대상이 아닙니다.")
            print("→ 스캔본이거나 괘선 없는 표일 수 있습니다. 기존 티어(assess_document.py 추천)를 쓰세요.")
        return False
    if result["cross"] is None:
        # 교차 대조 없는 PASS는 이 티어의 약속을 충족하지 않는다.
        print("오류: PyMuPDF(fitz)를 찾을 수 없어 PDF 추출 구현 간 교차 대조를 할 수 없습니다.")
        print("설치 명령: pip install -U pymupdf")
        print("→ 출력 파일을 만들지 않았습니다. 설치 후 재실행하거나 기존 티어로 승격하세요.")
        return False

    note = ""
    if not result["ok"] and strategy == "lines":
        # 배경 무늬 같은 작은 장식 도형이 격자로 잡힌 문서를 위한 재시도. 통과 기준은 같다.
        print(f"→ 무늬를 이루는 작은 채움 도형({DECOR_MIN_PT}~{DECOR_MAX_PT}pt, 선 없음)을 격자 후보에서 빼고 한 번 더 시도합니다.")
        retry = _attempt(filename, strategy, drop_decor=True, stream=stream)
        if retry is not None and retry["cross"] is not None and retry["ok"]:
            result = retry
            note = " (무늬를 이루는 작은 채움 도형 제외)"

    if not result["ok"]:
        print("→ 자가검증 실패: 출력 파일을 만들지 않았습니다. 기존 티어(LlamaParse v2·Upstage)로 승격하세요.")
        return False

    with open(output_file, "w", encoding="utf-8") as f:
        if result["straddles"]:
            # 어느 칸인지 모호한 자리를 산출물에 남겨 원본 확인 지점을 잃지 않는다
            f.write("<!-- 경계선에 걸친 글자(위아래 칸 배정 모호, 원본 확인): "
                    + "; ".join(result["straddles"]).replace("--", "- -") + " -->\n\n")
        f.write("\n\n".join(s for s in result["sections"] if s) + "\n")
    print(f"출력 파일: {output_file}")
    print(f"=== PASS: 열 배정과 PDF 추출 구현 간 교차 대조 일치{note} ===")
    return True


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    try:
        import pdfplumber  # noqa: F401
    except ImportError as e:
        print("오류: pdfplumber 패키지를 찾을 수 없습니다.")
        print("설치 명령: pip install pdfplumber")
        print(f"상세: {e}")
        return 1

    args = sys.argv[1:]
    strategy = "lines"
    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--strategy" and i + 1 < len(args):
            strategy = args[i + 1]
            i += 2
            continue
        if not args[i].startswith("--"):
            positional.append(args[i])
        i += 1
    if strategy not in ("lines", "text"):
        print(f"오류: 지원하지 않는 전략입니다: {strategy} (lines | text)")
        return 1

    if positional:
        return 0 if process_file(positional[0], strategy) else 1

    supported_files = sorted(
        f for f in os.listdir(".")
        if os.path.isfile(f) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
    )
    if not supported_files:
        print("오류: 현재 디렉토리에 지원되는 PDF 파일이 없습니다.")
        print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
        return 1
    if len(supported_files) == 1:
        return 0 if process_file(supported_files[0], strategy) else 1
    print(f"PDF 파일 {len(supported_files)}개 발견:")
    for i, f in enumerate(supported_files, 1):
        print(f"  {i}. {f}")
    print()
    all_ok = True
    for f in supported_files:
        all_ok = process_file(f, strategy) and all_ok
        print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        # Windows 한국어 콘솔(cp949)에서 출력이 깨지거나 예외가 나지 않게 한다. 실행할 때만 바꾼다.
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if __doc__ and any(_arg in ("--help", "-h") for _arg in sys.argv[1:]):
        print(__doc__.strip())
        sys.exit(0)
    exit_code = 1
    try:
        exit_code = main()
    except Exception as e:
        print(f"\n오류 발생: {e}")
        print("\n상세 정보:")
        traceback.print_exc()

    # 비-TTY(AI 에이전트·파이프·백그라운드)에서는 stdin이 EOF로 닫히지 않아
    # input()이 무한 블록되므로 isatty()로 가드 (다른 *_parse.py와 동일 패턴).
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nEnter를 눌러 종료...")
        except EOFError:
            pass
    sys.exit(exit_code)
