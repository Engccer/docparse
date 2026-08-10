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
셀(None 셀)도 span 정보가 평탄화되므로 감지 즉시 경고 대상이다. 경고가 하나라도
있으면 출력 파일을 만들지 않는다 — 기존 티어(LlamaParse v2·Upstage 등)로 승격할 것.

한계: 스캔본(텍스트 레이어 없음)은 출력 0(OCR 기능 없음), 괘선 없는 표는
정렬 추정이라 신뢰도 급락, 병합·rowspan 셀은 격자 모델이 깨짐, 다단 산문·헤딩
위계는 범위 밖. 해당 문서는 기존 티어 파이프라인을 그대로 쓴다.
"""
import os
import sys
import traceback

# Windows cp949 안전 (opendataloader_parse.py와 동일 패턴: 양쪽 스트림 + replace)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SUPPORTED_EXTENSIONS = [".pdf"]
MAX_PROBLEM_SAMPLES = 10  # 경고 출력 시 예시 상한


def get_output_filename(input_file):
    """입력 파일 경로 기반 출력 경로(<base>_pdfplumber.md) 생성."""
    dir_path = os.path.dirname(input_file)
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_name = f"{base_name}_pdfplumber.md"
    return os.path.join(dir_path, output_name) if dir_path else output_name


def _cell_md(value):
    """셀 텍스트를 마크다운 표 셀로: 내부 개행·연속 공백은 한 칸으로, 파이프 이스케이프."""
    if value is None:
        return ""
    return " ".join(value.split()).replace("|", "\\|")


def _grid_to_markdown(grid):
    """extract_tables() 격자를 마크다운 표로. 빈 셀은 빈 칸으로 보존."""
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


def _page_body(page, tables, grids):
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
    for table, grid in zip(tables, grids):
        md = _grid_to_markdown(grid)
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


def process_file(filename):
    import pdfplumber

    print(f"입력 파일: {filename}")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
        print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
        return
    if not os.path.exists(filename):
        print(f"오류: 파일을 찾을 수 없습니다: {filename}")
        return

    print("추출 중... (pdfplumber 격자 모델 + 좌표 재배치 자가검증)")
    sections = []
    total_tables = 0
    total_cells = 0
    total_nonempty = 0
    total_checked = 0
    merged_cells = 0
    all_problems = []
    all_unassigned = []

    with pdfplumber.open(filename) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            grids = [t.extract() for t in tables]
            for table in tables:
                # 병합(colspan/rowspan) 셀은 None 셀로 나타나고 span 정보가
                # 평탄화되므로, 좌표 대조가 일치해도 경고 대상이다.
                merged_cells += sum(
                    1 for row in table.rows for cell in row.cells if cell is None
                )
            for grid in grids:
                for row in grid:
                    total_cells += len(row)
                    total_nonempty += sum(1 for v in row if v and v.strip())
            total_tables += len(tables)

            body = _page_body(page, tables, grids)
            if page_count > 1:
                body.insert(0, f"## 페이지 {i}")
            sections.append("\n\n".join(body))

            assignments, unassigned = _assign_words_to_cells(page, tables)
            checked, problems = verify_page(grids, assignments)
            total_checked += checked
            all_problems.extend((i, *p) for p in problems)
            all_unassigned.extend((i, t) for t in unassigned)

    if total_tables == 0:
        print("경고: 괘선 표를 하나도 찾지 못했습니다. 이 문서는 Tier 0 대상이 아닙니다.")
        print("→ 스캔본이거나 괘선 없는 표일 수 있습니다. 기존 티어(assess_document.py 추천)를 쓰세요.")
        return

    print(f"페이지 {page_count} · 표 {total_tables}개 · 셀 {total_cells}개(내용 있는 셀 {total_nonempty})")
    print(f"자가검증(격자 추출 ↔ 좌표 재배치 양방향 대조): 셀 {total_checked}건")

    if all_problems or all_unassigned or merged_cells:
        print(f"경고: 셀 불일치 {len(all_problems)}건 · 미배정 단어 {len(all_unassigned)}건 · 병합 의심 셀 {merged_cells}건")
        for page_no, ti, r, c, a, b in all_problems[:MAX_PROBLEM_SAMPLES]:
            print(f"  - p{page_no} 표{ti + 1} ({r},{c}): 격자='{a}' / 좌표='{b}'")
        if len(all_problems) > MAX_PROBLEM_SAMPLES:
            print(f"  ... 외 {len(all_problems) - MAX_PROBLEM_SAMPLES}건")
        if all_unassigned:
            samples = ", ".join(t for _, t in all_unassigned[:MAX_PROBLEM_SAMPLES])
            print(f"  - 미배정(병합 셀·경계 걸침 의심): {samples}")
        if merged_cells:
            print("  - 병합 셀은 마크다운 표에서 span 정보가 소실됩니다")
        print("→ 자가검증 실패: 출력 파일을 만들지 않았습니다. 기존 티어(LlamaParse v2·Upstage)로 승격하세요.")
        return

    output_file = get_output_filename(filename)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(s for s in sections if s) + "\n")
    print(f"출력 파일: {output_file}")
    print("=== PASS: 열 배정까지 완전 일치 ===")


def main():
    try:
        import pdfplumber  # noqa: F401
    except ImportError as e:
        print("오류: pdfplumber 패키지를 찾을 수 없습니다.")
        print("설치 명령: pip install pdfplumber")
        print(f"상세: {e}")
        return

    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    if positional:
        process_file(positional[0])
        return

    supported_files = sorted(
        f for f in os.listdir(".")
        if os.path.isfile(f) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
    )
    if not supported_files:
        print("오류: 현재 디렉토리에 지원되는 PDF 파일이 없습니다.")
        print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
        return
    if len(supported_files) == 1:
        process_file(supported_files[0])
        return
    print(f"PDF 파일 {len(supported_files)}개 발견:")
    for i, f in enumerate(supported_files, 1):
        print(f"  {i}. {f}")
    print()
    for f in supported_files:
        process_file(f)
        print()


if __name__ == "__main__":
    try:
        main()
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
